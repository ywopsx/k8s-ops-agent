"""업그레이드 전에 확인할 항목들.

각 check 함수는 Snapshot과 Context를 받아 Finding 목록을 돌려준다.
모든 check는 읽기 전용이며 클러스터를 변경하지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .models import Finding, Severity, Snapshot, version_tuple
from .removed_apis import REMOVED_APIS

# 노드그룹 이름을 담는 라벨. 노드그룹을 새로 만들면 이름이 바뀌어 스케줄링이 깨진다.
NODEGROUP_LABELS = ("eks.amazonaws.com/nodegroup", "alpha.eksctl.io/nodegroup-name")

SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}

WORKLOAD_KINDS = ("deployments", "statefulsets", "daemonsets", "jobs", "cronjobs")

LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"


@dataclass
class Context:
    target_version: str
    # VPC CNI(aws-node)에서 업그레이드 후에도 유지돼야 하는 환경변수 기준값
    cni_expected_env: dict[str, str] = field(default_factory=dict)
    include_system: bool = False

    @property
    def target(self) -> tuple[int, int]:
        return version_tuple(self.target_version)


def _meta(obj: dict) -> tuple[str, str | None]:
    md = obj.get("metadata", {})
    return md.get("name", "?"), md.get("namespace")


def _pod_spec(kind: str, obj: dict) -> dict:
    spec = obj.get("spec", {})
    if kind == "cronjobs":
        return spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {})
    if kind == "pods":
        return spec
    return spec.get("template", {}).get("spec", {})


def _kind_label(kind: str) -> str:
    return {
        "deployments": "Deployment", "statefulsets": "StatefulSet", "daemonsets": "DaemonSet",
        "jobs": "Job", "cronjobs": "CronJob", "pods": "Pod", "nodes": "Node",
        "poddisruptionbudgets": "PodDisruptionBudget", "services": "Service", "ingresses": "Ingress",
        "targetgroupbindings": "TargetGroupBinding",
    }.get(kind, kind)


def _skip_ns(ns: str | None, ctx: Context) -> bool:
    return (not ctx.include_system) and ns in SYSTEM_NAMESPACES


# ---------------------------------------------------------------------------
# 1. 노드그룹 이름에 묶인 스케줄링
# ---------------------------------------------------------------------------
def check_nodegroup_pinned(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []
    for kind in WORKLOAD_KINDS:
        for obj in snap.items(kind):
            name, ns = _meta(obj)
            spec = _pod_spec(kind, obj)
            hits = [k for k in spec.get("nodeSelector", {}) if k in NODEGROUP_LABELS]
            affinity = spec.get("affinity", {}).get("nodeAffinity", {})
            required = affinity.get("requiredDuringSchedulingIgnoredDuringExecution", {})
            for term in required.get("nodeSelectorTerms", []):
                hits += [e["key"] for e in term.get("matchExpressions", []) if e.get("key") in NODEGROUP_LABELS]
            if hits:
                findings.append(Finding(
                    check="nodegroup-pinned", severity=Severity.HIGH, kind=_kind_label(kind), name=name, namespace=ns,
                    message=f"노드그룹 이름 라벨({', '.join(sorted(set(hits)))})로 스케줄링이 고정돼 있어, "
                            "노드그룹을 새로 만들어 교체하면 새 노드로 옮겨 가지 못합니다.",
                    hint="노드그룹마다 공통으로 붙는 역할 라벨(예: node-role: app)로 바꾼 뒤 노드그룹을 교체하세요.",
                ))
    return findings


# ---------------------------------------------------------------------------
# 2. drain을 막는 PDB
# ---------------------------------------------------------------------------
def check_pdb_blocks_drain(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []
    for pdb in snap.items("poddisruptionbudgets"):
        name, ns = _meta(pdb)
        if _skip_ns(ns, ctx):
            continue
        status = pdb.get("status", {})
        expected = status.get("expectedPods", 0)
        allowed = status.get("disruptionsAllowed")
        spec = pdb.get("spec", {})
        if expected > 0 and allowed == 0:
            findings.append(Finding(
                check="pdb-blocks-drain", severity=Severity.HIGH, kind="PodDisruptionBudget", name=name, namespace=ns,
                message=f"현재 허용된 중단 수가 0입니다(대상 Pod {expected}개). 노드 drain이 이 지점에서 멈춥니다.",
                hint="replica를 늘리거나 minAvailable/maxUnavailable을 조정한 뒤 노드를 교체하세요.",
            ))
        elif str(spec.get("maxUnavailable")) in ("0", "0%"):
            findings.append(Finding(
                check="pdb-blocks-drain", severity=Severity.HIGH, kind="PodDisruptionBudget", name=name, namespace=ns,
                message="maxUnavailable이 0이라 어떤 Pod도 evict될 수 없습니다.",
                hint="업그레이드 기간에는 maxUnavailable을 1 이상으로 두세요.",
            ))
    return findings


# ---------------------------------------------------------------------------
# 3. 컨트롤러 없는 단독 Pod
# ---------------------------------------------------------------------------
def check_unmanaged_pods(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []
    for pod in snap.items("pods"):
        name, ns = _meta(pod)
        md = pod.get("metadata", {})
        if _skip_ns(ns, ctx) or "kubernetes.io/config.mirror" in md.get("annotations", {}):
            continue
        if not md.get("ownerReferences"):
            findings.append(Finding(
                check="unmanaged-pod", severity=Severity.MEDIUM, kind="Pod", name=name, namespace=ns,
                message="컨트롤러(Deployment 등) 없이 떠 있는 Pod라, 노드가 교체되면 다시 생성되지 않습니다.",
                hint="Deployment나 Job으로 옮기거나, 노드 교체 전에 담당자와 처리 방법을 정하세요.",
            ))
    return findings


# ---------------------------------------------------------------------------
# 4. replica 1개 워크로드
# ---------------------------------------------------------------------------
def check_single_replica(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []
    for kind in ("deployments", "statefulsets"):
        for obj in snap.items(kind):
            name, ns = _meta(obj)
            if _skip_ns(ns, ctx):
                continue
            replicas = obj.get("spec", {}).get("replicas", 1)
            if replicas == 1:
                findings.append(Finding(
                    check="single-replica", severity=Severity.MEDIUM, kind=_kind_label(kind), name=name, namespace=ns,
                    message="replica가 1개라 노드 교체 중 서비스가 잠시 끊길 수 있습니다.",
                    hint="업그레이드 기간에만 replica를 늘리거나, 영향을 받아도 되는 서비스인지 확인하세요.",
                ))
    return findings


# ---------------------------------------------------------------------------
# 5. 대상 버전에서 제거된 API
# ---------------------------------------------------------------------------
def check_removed_apis(snap: Snapshot, ctx: Context) -> list[Finding]:
    """마지막으로 apply된 매니페스트(last-applied-configuration)의 apiVersion을 본다.

    API 서버는 저장된 객체를 지원하는 버전으로 바꿔서 돌려주기 때문에, 조회 결과의
    apiVersion만으로는 매니페스트가 옛 버전으로 작성됐는지 알 수 없다.
    """
    findings = []
    for _, obj in snap.all_items():
        raw = obj.get("metadata", {}).get("annotations", {}).get(LAST_APPLIED)
        if not raw:
            continue
        try:
            applied = json.loads(raw)
        except json.JSONDecodeError:
            continue
        key = (applied.get("apiVersion", ""), applied.get("kind", ""))
        if key not in REMOVED_APIS:
            continue
        removed_in, replacement = REMOVED_APIS[key]
        if removed_in <= ctx.target:
            name, ns = _meta(obj)
            findings.append(Finding(
                check="removed-api", severity=Severity.HIGH, kind=key[1], name=name, namespace=ns,
                message=f"{key[0]} {key[1]}로 작성된 매니페스트입니다. 이 API는 {removed_in[0]}.{removed_in[1]}에서 제거됐습니다.",
                hint=f"매니페스트(또는 Helm 차트)를 {replacement}로 바꾼 뒤 다시 배포하세요.",
            ))
    return findings


# ---------------------------------------------------------------------------
# 6. 대상 버전에서 쓸 수 없는 AL2 노드
# ---------------------------------------------------------------------------
def check_al2_nodes(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []
    for node in snap.items("nodes"):
        name, _ = _meta(node)
        os_image = node.get("status", {}).get("nodeInfo", {}).get("osImage", "")
        if os_image.startswith("Amazon Linux 2") and not os_image.startswith("Amazon Linux 2023"):
            sev = Severity.HIGH if ctx.target >= (1, 33) else Severity.MEDIUM
            findings.append(Finding(
                check="al2-node", severity=sev, kind="Node", name=name, namespace=None,
                message=f"노드 OS가 {os_image}입니다. EKS는 1.33부터 AL2용 최적화 AMI를 제공하지 않습니다.",
                hint="업그레이드 전에 AL2023(또는 Bottlerocket) 노드그룹을 병행 생성해 워크로드를 옮기세요.",
            ))
    return findings


# ---------------------------------------------------------------------------
# 7. VPC CNI(aws-node) 설정 스냅샷
# ---------------------------------------------------------------------------
def check_vpc_cni_env(snap: Snapshot, ctx: Context) -> list[Finding]:
    ds = next((d for d in snap.items("daemonsets")
               if d.get("metadata", {}).get("name") == "aws-node"
               and d.get("metadata", {}).get("namespace") == "kube-system"), None)
    if ds is None:
        return []
    env: dict[str, str] = {}
    for c in ds.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
        for e in c.get("env", []):
            if "value" in e:
                env[e["name"]] = str(e["value"])
    findings = []
    mismatched = {k: (v, env.get(k)) for k, v in ctx.cni_expected_env.items() if env.get(k) != v}
    for key, (want, got) in mismatched.items():
        findings.append(Finding(
            check="vpc-cni-env", severity=Severity.HIGH, kind="DaemonSet", name="aws-node", namespace="kube-system",
            message=f"{key}가 기준값 {want!r}와 다릅니다(현재 {got!r}).",
            hint="vpc-cni add-on을 업데이트할 때 resolve_conflicts를 PRESERVE로 두고, 설정을 기준값으로 되돌리세요.",
        ))
    watched = {k: env[k] for k in sorted(env) if k.startswith(("AWS_VPC_", "ENABLE_", "ENI_CONFIG", "WARM_"))}
    findings.append(Finding(
        check="vpc-cni-env", severity=Severity.INFO, kind="DaemonSet", name="aws-node", namespace="kube-system",
        message="현재 VPC CNI 설정: " + (", ".join(f"{k}={v}" for k, v in watched.items()) or "(주요 설정 없음)"),
        hint="이 값을 기준값 파일로 저장해 두고, add-on 업데이트 뒤 --cni-baseline으로 다시 비교하세요.",
    ))
    return findings


# ---------------------------------------------------------------------------
# 8. instance 타입 로드밸런서 대상 (Karpenter 전환 준비)
# ---------------------------------------------------------------------------
# AWS Load Balancer Controller(LBC)가 쓰는 IngressClass 컨트롤러 이름과 어노테이션
ALB_CONTROLLER = "ingress.k8s.aws/alb"
ALB_TARGET_TYPE = "alb.ingress.kubernetes.io/target-type"
NLB_TYPE = "service.beta.kubernetes.io/aws-load-balancer-type"
NLB_TARGET_TYPE = "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type"
LBC_NLB_CLASS = "service.k8s.aws/nlb"

LB_INSTANCE_MESSAGE = ("instance 모드는 Pod가 아니라 노드(NodePort)로 트래픽을 보냅니다. Karpenter가 노드를 "
                       "통합·교체할 때 처리 중인 요청이 끊기거나, 크기가 다른 노드로 트래픽이 쏠릴 수 있습니다. "
                       "대상 그룹을 클러스터 밖에서 ASG에 직접 붙였다면 Karpenter 노드는 아예 등록되지 않습니다"
                       "(이 경우는 클러스터 리소스로 확인할 수 없습니다).")
LB_INSTANCE_HINT = "Karpenter로 옮기기 전에 target type을 ip로 바꾸고, Pod readiness gate 적용을 검토하세요."


def _alb_class_names(snap: Snapshot) -> tuple[set[str], str | None]:
    """LBC가 처리하는 IngressClass 이름들과 기본 IngressClass 이름(LBC 것일 때만)."""
    names, default = {"alb"}, None
    for ic in snap.items("ingressclasses"):
        if ic.get("spec", {}).get("controller") != ALB_CONTROLLER:
            continue
        name, _ = _meta(ic)
        names.add(name)
        if ic.get("metadata", {}).get("annotations", {}).get("ingressclass.kubernetes.io/is-default-class") == "true":
            default = name
    return names, default


def check_lb_target_instance(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []

    def add(kind: str, obj: dict, detail: str) -> None:
        name, ns = _meta(obj)
        findings.append(Finding(
            check="lb-target-instance", severity=Severity.MEDIUM, kind=kind, name=name, namespace=ns,
            message=f"{detail} {LB_INSTANCE_MESSAGE}", hint=LB_INSTANCE_HINT,
        ))

    alb_classes, default_class = _alb_class_names(snap)
    for ing in snap.items("ingresses"):
        _, ns = _meta(ing)
        if _skip_ns(ns, ctx):
            continue
        ann = ing.get("metadata", {}).get("annotations", {})
        cls = ing.get("spec", {}).get("ingressClassName") or ann.get("kubernetes.io/ingress.class") or default_class
        if cls not in alb_classes:
            continue
        target = ann.get(ALB_TARGET_TYPE, "instance")
        if target == "instance":
            how = "명시돼 있습니다" if ALB_TARGET_TYPE in ann else "지정되지 않아 기본값 instance로 동작합니다"
            add("Ingress", ing, f"ALB target-type이 {how}.")

    for svc in snap.items("services"):
        _, ns = _meta(svc)
        spec = svc.get("spec", {})
        if _skip_ns(ns, ctx) or spec.get("type") != "LoadBalancer":
            continue
        ann = svc.get("metadata", {}).get("annotations", {})
        lb_class = spec.get("loadBalancerClass")
        lb_type = ann.get(NLB_TYPE, "")
        if lb_type == "nlb-ip":
            continue  # 예전 LBC 방식의 ip 모드
        if lb_class == LBC_NLB_CLASS or lb_type == "external":
            target = ann.get(NLB_TARGET_TYPE, "instance")
            if target == "instance":
                how = "명시돼 있습니다" if NLB_TARGET_TYPE in ann else "지정되지 않아 기본값 instance로 동작합니다"
                add("Service", svc, f"NLB target type이 {how}.")
        elif lb_class is None:
            add("Service", svc, f"쿠버네티스 내장 컨트롤러가 만드는 {'NLB' if lb_type == 'nlb' else 'CLB'}라 "
                                "항상 노드를 대상으로 등록합니다.")
        # 그 밖의 loadBalancerClass는 다른 컨트롤러가 처리하므로 판단하지 않는다.

    for tgb in snap.items("targetgroupbindings"):
        _, ns = _meta(tgb)
        if _skip_ns(ns, ctx):
            continue
        # targetType이 비어 있으면 LBC가 대상 그룹 설정을 따르므로 클러스터 리소스만으로는 알 수 없다.
        if tgb.get("spec", {}).get("targetType") == "instance":
            add("TargetGroupBinding", tgb, "targetType이 instance입니다.")
    return findings


# ---------------------------------------------------------------------------
# 9. AZ 분산 제약 (Karpenter 전환 준비)
# ---------------------------------------------------------------------------
ZONE_KEYS = ("topology.kubernetes.io/zone", "failure-domain.beta.kubernetes.io/zone")


def check_topology_spread(snap: Snapshot, ctx: Context) -> list[Finding]:
    findings = []
    for kind in ("deployments", "statefulsets"):
        for obj in snap.items(kind):
            name, ns = _meta(obj)
            if _skip_ns(ns, ctx):
                continue
            spec = _pod_spec(kind, obj)
            hard, soft, no_min_domains = [], [], False
            for c in spec.get("topologySpreadConstraints", []):
                if c.get("topologyKey") not in ZONE_KEYS:
                    continue
                # whenUnsatisfiable의 기본값은 DoNotSchedule
                mode = c.get("whenUnsatisfiable", "DoNotSchedule")
                desc = f"topologySpreadConstraints(maxSkew={c.get('maxSkew', 1)}, {mode})"
                if mode == "DoNotSchedule":
                    hard.append(desc)
                    no_min_domains |= "minDomains" not in c
                else:
                    soft.append(desc)
            anti = spec.get("affinity", {}).get("podAntiAffinity", {})
            if any(t.get("topologyKey") in ZONE_KEYS
                   for t in anti.get("requiredDuringSchedulingIgnoredDuringExecution", [])):
                hard.append("필수 podAntiAffinity(AZ 키)")
            if not (hard or soft):
                continue
            replicas = obj.get("spec", {}).get("replicas", 1)
            if hard:
                hint = "Karpenter NodePool의 topology.kubernetes.io/zone 요구사항과 서브넷이 대상 AZ를 모두 포함하는지 확인하세요."
                if no_min_domains:
                    hint += (" minDomains가 없으면 스케줄러는 지금 노드가 있는 AZ만 기준으로 분산하므로, "
                             "새 AZ에 노드를 늘리려면 minDomains를 함께 설정하세요.")
                findings.append(Finding(
                    check="topology-spread", severity=Severity.MEDIUM, kind=_kind_label(kind), name=name, namespace=ns,
                    message=f"AZ 분산을 강제하는 제약이 있습니다: {', '.join(hard)}, replica {replicas}. "
                            "NodePool·서브넷이 일부 AZ에만 열려 있거나 노드 교체 중 한 AZ의 노드가 비면 "
                            "새 Pod가 Pending으로 남을 수 있습니다.",
                    hint=hint,
                ))
            else:
                findings.append(Finding(
                    check="topology-spread", severity=Severity.INFO, kind=_kind_label(kind), name=name, namespace=ns,
                    message=f"AZ 분산 선호 제약이 있습니다: {', '.join(soft)}, replica {replicas}. "
                            "조건을 못 맞춰도 스케줄링은 되지만 한 AZ에 몰릴 수 있습니다.",
                    hint="Karpenter 전환 후 Pod가 AZ별로 어떻게 배치됐는지 확인하세요.",
                ))
    return findings


ALL_CHECKS: list[Callable[[Snapshot, Context], list[Finding]]] = [
    check_nodegroup_pinned,
    check_pdb_blocks_drain,
    check_unmanaged_pods,
    check_single_replica,
    check_removed_apis,
    check_al2_nodes,
    check_vpc_cni_env,
    check_lb_target_instance,
    check_topology_spread,
]


def run_all(snap: Snapshot, ctx: Context, checks: Iterable = ALL_CHECKS) -> list[Finding]:
    findings: list[Finding] = []
    for check in checks:
        findings.extend(check(snap, ctx))
    return sorted(findings, key=lambda f: (-f.severity, f.check, f.ref))
