import json

import pytest

from preflight.checks import (
    Context, check_al2_nodes, check_colocated_replicas, check_lb_target_instance, check_nodegroup_pinned,
    check_pdb_blocks_drain, check_removed_apis, check_single_replica, check_topology_spread, check_unmanaged_pods,
    check_vpc_cni_env, run_all, selector_matches,
)
from preflight.models import Severity, Snapshot, version_tuple

CTX = Context(target_version="1.33")


def deployment(name="web", ns="app", replicas=2, node_selector=None, affinity=None):
    spec = {"nodeSelector": node_selector or {}}
    if affinity:
        spec["affinity"] = affinity
    return {"metadata": {"name": name, "namespace": ns},
            "spec": {"replicas": replicas, "template": {"spec": spec}}}


# --- nodegroup-pinned ------------------------------------------------------
def test_nodegroup_pinned_by_node_selector():
    snap = Snapshot({"deployments": [deployment(node_selector={"eks.amazonaws.com/nodegroup": "ng-legacy"})]})
    [f] = check_nodegroup_pinned(snap, CTX)
    assert f.severity == Severity.HIGH and f.ref == "Deployment/app/web"


def test_nodegroup_pinned_by_affinity_and_cronjob():
    aff = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
        {"matchExpressions": [{"key": "eks.amazonaws.com/nodegroup", "operator": "In", "values": ["ng-a"]}]}]}}}
    cron = {"metadata": {"name": "batch", "namespace": "app"},
            "spec": {"jobTemplate": {"spec": {"template": {"spec": {"affinity": aff}}}}}}
    snap = Snapshot({"cronjobs": [cron]})
    assert [f.ref for f in check_nodegroup_pinned(snap, CTX)] == ["CronJob/app/batch"]


def test_role_label_is_not_flagged():
    snap = Snapshot({"deployments": [deployment(node_selector={"node-role": "app"})]})
    assert check_nodegroup_pinned(snap, CTX) == []


def test_platform_pods_in_kube_system_are_still_checked():
    # 실무에서 문제였던 건 kube-system의 플랫폼 Pod(LB Controller 등)였다.
    snap = Snapshot({"deployments": [deployment(ns="kube-system",
                                                node_selector={"eks.amazonaws.com/nodegroup": "mgmt"})]})
    assert len(check_nodegroup_pinned(snap, CTX)) == 1


# --- pdb-blocks-drain ------------------------------------------------------
def test_pdb_with_zero_disruptions_allowed():
    pdb = {"metadata": {"name": "web", "namespace": "app"}, "spec": {"minAvailable": 1},
           "status": {"expectedPods": 1, "disruptionsAllowed": 0}}
    [f] = check_pdb_blocks_drain(Snapshot({"poddisruptionbudgets": [pdb]}), CTX)
    assert f.check == "pdb-blocks-drain"


def test_pdb_with_room_is_ok():
    pdb = {"metadata": {"name": "web", "namespace": "app"}, "spec": {"minAvailable": 1},
           "status": {"expectedPods": 3, "disruptionsAllowed": 2}}
    assert check_pdb_blocks_drain(Snapshot({"poddisruptionbudgets": [pdb]}), CTX) == []


# --- unmanaged-pod / single-replica ---------------------------------------
def test_unmanaged_pod_and_mirror_pod():
    bare = {"metadata": {"name": "debug", "namespace": "app"}}
    mirror = {"metadata": {"name": "etcd", "namespace": "app",
                           "annotations": {"kubernetes.io/config.mirror": "x"}}}
    owned = {"metadata": {"name": "web-1", "namespace": "app", "ownerReferences": [{"kind": "ReplicaSet"}]}}
    found = check_unmanaged_pods(Snapshot({"pods": [bare, mirror, owned]}), CTX)
    assert [f.name for f in found] == ["debug"]


def test_single_replica_skips_system_namespaces_by_default():
    snap = Snapshot({"deployments": [deployment(replicas=1), deployment(name="dns", ns="kube-system", replicas=1)]})
    assert [f.name for f in check_single_replica(snap, CTX)] == ["web"]
    ctx = Context(target_version="1.33", include_system=True)
    assert len(check_single_replica(snap, ctx)) == 2


# --- removed-api -----------------------------------------------------------
def with_last_applied(obj, api_version, kind):
    obj.setdefault("metadata", {}).setdefault("annotations", {})[
        "kubectl.kubernetes.io/last-applied-configuration"] = json.dumps({"apiVersion": api_version, "kind": kind})
    return obj


@pytest.mark.parametrize("target,expected", [("1.31", 0), ("1.32", 1), ("1.35", 1)])
def test_flowschema_v1beta3_removed_in_132(target, expected):
    fs = with_last_applied({"metadata": {"name": "custom"}}, "flowcontrol.apiserver.k8s.io/v1beta3", "FlowSchema")
    found = check_removed_apis(Snapshot({"flowschemas": [fs]}), Context(target_version=target))
    assert len(found) == expected


def test_current_api_is_not_flagged():
    ing = with_last_applied({"metadata": {"name": "web", "namespace": "app"}}, "networking.k8s.io/v1", "Ingress")
    assert check_removed_apis(Snapshot({"ingresses": [ing]}), CTX) == []


# --- al2-node --------------------------------------------------------------
def node(name, os_image):
    return {"metadata": {"name": name}, "status": {"nodeInfo": {"osImage": os_image}}}


def test_al2_nodes_are_high_from_133():
    snap = Snapshot({"nodes": [node("a", "Amazon Linux 2"), node("b", "Amazon Linux 2023.6.20250115")]})
    [f] = check_al2_nodes(snap, Context(target_version="1.33"))
    assert f.name == "a" and f.severity == Severity.HIGH
    [f] = check_al2_nodes(snap, Context(target_version="1.32"))
    assert f.severity == Severity.MEDIUM


# --- vpc-cni-env -----------------------------------------------------------
def aws_node(env):
    return {"metadata": {"name": "aws-node", "namespace": "kube-system"},
            "spec": {"template": {"spec": {"containers": [
                {"name": "aws-node", "env": [{"name": k, "value": v} for k, v in env.items()]}]}}}}


def test_cni_overwritten_settings_are_detected():
    # add-on 업데이트로 Custom Networking 설정이 기본값으로 덮어써진 상황을 재현
    snap = Snapshot({"daemonsets": [aws_node({"AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "false",
                                               "ENABLE_PREFIX_DELEGATION": "true"})]})
    ctx = Context(target_version="1.33", cni_expected_env={"AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "true",
                                                            "ENABLE_PREFIX_DELEGATION": "true"})
    found = check_vpc_cni_env(snap, ctx)
    high = [f for f in found if f.severity == Severity.HIGH]
    assert len(high) == 1 and "AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG" in high[0].message
    assert any(f.severity == Severity.INFO for f in found)


def test_no_aws_node_means_no_cni_findings():
    assert check_vpc_cni_env(Snapshot({"daemonsets": []}), CTX) == []


# --- lb-target-instance ----------------------------------------------------
def ingress(name="web", ns="app", cls="alb", annotations=None, class_annotation=False):
    md = {"name": name, "namespace": ns, "annotations": dict(annotations or {})}
    spec = {}
    if cls and class_annotation:
        md["annotations"]["kubernetes.io/ingress.class"] = cls
    elif cls:
        spec["ingressClassName"] = cls
    return {"metadata": md, "spec": spec}


def service(name="web", ns="app", svc_type="LoadBalancer", annotations=None, lb_class=None):
    spec = {"type": svc_type}
    if lb_class:
        spec["loadBalancerClass"] = lb_class
    return {"metadata": {"name": name, "namespace": ns, "annotations": annotations or {}}, "spec": spec}


def lb_refs(snap, ctx=CTX):
    return sorted(f.ref for f in check_lb_target_instance(snap, ctx))


def test_alb_ingress_defaults_to_instance():
    snap = Snapshot({"ingresses": [
        ingress("default"),
        ingress("explicit", annotations={"alb.ingress.kubernetes.io/target-type": "instance"}),
        ingress("legacy-annotation", class_annotation=True),
        ingress("ip", annotations={"alb.ingress.kubernetes.io/target-type": "ip"}),
        ingress("nginx", cls="nginx"),
    ]})
    found = check_lb_target_instance(snap, CTX)
    assert sorted(f.name for f in found) == ["default", "explicit", "legacy-annotation"]
    assert all(f.severity == Severity.MEDIUM for f in found)
    assert "기본값 instance" in next(f for f in found if f.name == "default").message


def test_alb_ingress_class_resolved_from_ingressclass():
    # 이름이 alb가 아니어도 컨트롤러가 LBC면 ALB로 본다. 클래스가 없으면 기본 IngressClass를 따른다.
    ic = {"metadata": {"name": "public", "annotations": {"ingressclass.kubernetes.io/is-default-class": "true"}},
          "spec": {"controller": "ingress.k8s.aws/alb"}}
    snap = Snapshot({"ingressclasses": [ic], "ingresses": [ingress("named", cls="public"), ingress("implicit", cls=None)]})
    assert lb_refs(snap) == ["Ingress/app/implicit", "Ingress/app/named"]


def test_nlb_service_target_types():
    t = "service.beta.kubernetes.io/aws-load-balancer-type"
    tt = "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type"
    snap = Snapshot({"services": [
        service("external-default", annotations={t: "external"}),
        service("class-default", lb_class="service.k8s.aws/nlb"),
        service("external-ip", annotations={t: "external", tt: "ip"}),
        service("legacy-nlb-ip", annotations={t: "nlb-ip"}),
        service("cluster-ip", svc_type="ClusterIP"),
        service("other-controller", lb_class="example.com/lb"),
    ]})
    assert lb_refs(snap) == ["Service/app/class-default", "Service/app/external-default"]


def test_in_tree_load_balancer_is_flagged():
    snap = Snapshot({"services": [service("clb"),
                                  service("nlb", annotations={"service.beta.kubernetes.io/aws-load-balancer-type": "nlb"})]})
    found = {f.name: f for f in check_lb_target_instance(snap, CTX)}
    assert "CLB" in found["clb"].message and "NLB" in found["nlb"].message


def test_target_group_binding():
    def tgb(name, target_type=None):
        spec = {"targetType": target_type} if target_type else {}
        return {"metadata": {"name": name, "namespace": "app"}, "spec": spec}
    snap = Snapshot({"targetgroupbindings": [tgb("inst", "instance"), tgb("ip", "ip"), tgb("unknown")]})
    assert lb_refs(snap) == ["TargetGroupBinding/app/inst"]


def test_lb_in_system_namespace_is_skipped_by_default():
    snap = Snapshot({"services": [service(ns="kube-system")]})
    assert lb_refs(snap) == []
    assert len(lb_refs(snap, Context(target_version="1.33", include_system=True))) == 1


# --- topology-spread -------------------------------------------------------
def spread(key="topology.kubernetes.io/zone", mode=None, **extra):
    c = {"maxSkew": 1, "topologyKey": key, **extra}
    if mode:
        c["whenUnsatisfiable"] = mode
    return c


def with_spread(obj, *constraints):
    obj["spec"]["template"]["spec"]["topologySpreadConstraints"] = list(constraints)
    return obj


def test_zone_do_not_schedule_is_medium_and_schedule_anyway_is_info():
    snap = Snapshot({"deployments": [
        with_spread(deployment("hard"), spread(mode="DoNotSchedule")),
        with_spread(deployment("default-mode"), spread()),  # 기본값은 DoNotSchedule
        with_spread(deployment("soft"), spread(mode="ScheduleAnyway")),
        with_spread(deployment("both"), spread(mode="ScheduleAnyway"), spread(mode="DoNotSchedule")),
    ]})
    found = {f.name: f.severity for f in check_topology_spread(snap, CTX)}
    assert found == {"hard": Severity.MEDIUM, "default-mode": Severity.MEDIUM,
                     "soft": Severity.INFO, "both": Severity.MEDIUM}


def test_hostname_spread_is_not_flagged():
    snap = Snapshot({"deployments": [with_spread(deployment(), spread(key="kubernetes.io/hostname"))]})
    assert check_topology_spread(snap, CTX) == []


def test_zone_pod_anti_affinity_and_statefulset():
    aff = {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
        {"topologyKey": "topology.kubernetes.io/zone", "labelSelector": {"matchLabels": {"app": "db"}}}]}}
    sts = deployment("db", affinity=aff)
    [f] = check_topology_spread(Snapshot({"statefulsets": [sts]}), CTX)
    assert f.ref == "StatefulSet/app/db" and f.severity == Severity.MEDIUM


def test_min_domains_hint():
    without = with_spread(deployment("a"), spread(mode="DoNotSchedule"))
    with_min = with_spread(deployment("b"), spread(mode="DoNotSchedule", minDomains=3))
    found = {f.name: f.hint for f in check_topology_spread(Snapshot({"deployments": [without, with_min]}), CTX)}
    assert "minDomains" in found["a"] and "minDomains" not in found["b"]


# --- 공통 -------------------------------------------------------------------
def test_run_all_sorts_high_first():
    snap = Snapshot({"deployments": [deployment(replicas=1, node_selector={"eks.amazonaws.com/nodegroup": "x"})]})
    found = run_all(snap, CTX)
    assert [f.severity for f in found] == sorted([f.severity for f in found], reverse=True)


def test_version_parsing():
    assert version_tuple("v1.33.2") == (1, 33)
    with pytest.raises(ValueError):
        version_tuple("latest")


# --- colocated-replicas ----------------------------------------------------
def selected_workload(name="web", ns="app", replicas=2, kind="deployments"):
    return {"metadata": {"name": name, "namespace": ns},
            "spec": {"replicas": replicas, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}}, "spec": {}}}}


def running_pod(name, node, app="web", ns="app", ready=True):
    return {"metadata": {"name": name, "namespace": ns, "labels": {"app": app},
                         "ownerReferences": [{"kind": "ReplicaSet"}]},
            "spec": {"nodeName": node},
            "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


def pdb_for(app="web", ns="app", **spec):
    return {"metadata": {"name": f"{app}-pdb", "namespace": ns},
            "spec": {"selector": {"matchLabels": {"app": app}}, **spec}}


def colocated(snap):
    return check_colocated_replicas(Snapshot(snap), CTX)


def test_colocated_replicas_without_pdb_is_medium():
    # drain 데모의 order-api: replica 2, PDB 없음, 두 Pod가 같은 노드 → 두 번째 Pod가 대체 Pod보다 먼저 evict됨
    [f] = colocated({"deployments": [selected_workload()],
                     "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a")]})
    assert f.check == "colocated-replicas" and f.severity == Severity.MEDIUM and f.ref == "Deployment/app/web"
    assert "node-a" in f.message and "PDB가 없습니다" in f.message


def test_replicas_spread_across_nodes_are_ok():
    assert colocated({"deployments": [selected_workload()],
                      "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-b")]}) == []


def test_only_ready_pods_count():
    # Ready Pod가 2개 미만이면 검출하지 않는다 (NotReady·Pending Pod는 세지 않음)
    pending = running_pod("web-3", "node-a")
    pending["spec"] = {}
    assert colocated({"deployments": [selected_workload()],
                      "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a", ready=False),
                               pending]}) == []


def test_single_replica_is_left_to_single_replica_check():
    assert colocated({"deployments": [selected_workload(replicas=1)],
                      "pods": [running_pod("web-1", "node-a")]}) == []


def test_pods_of_other_workloads_and_namespaces_are_not_mixed():
    assert colocated({"deployments": [selected_workload()],
                      "pods": [running_pod("web-1", "node-a"), running_pod("api-1", "node-a", app="api"),
                               running_pod("web-x", "node-a", ns="other")]}) == []


@pytest.mark.parametrize("spec", [{"maxUnavailable": 1}, {"maxUnavailable": "50%"}, {"minAvailable": 1},
                                  {"minAvailable": "50%"}])
def test_protective_pdb_prevents_finding(spec):
    # 두 번째 eviction이 첫 대체 Pod가 Ready가 될 때까지 막히므로 다운타임이 없다
    assert colocated({"deployments": [selected_workload()], "poddisruptionbudgets": [pdb_for(**spec)],
                      "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a")]}) == []


@pytest.mark.parametrize("spec, shown", [({"maxUnavailable": 2}, "maxUnavailable=2"),
                                         ({"maxUnavailable": 3}, "maxUnavailable=3"),
                                         ({"maxUnavailable": "100%"}, "maxUnavailable=100%"),
                                         ({"minAvailable": 0}, "minAvailable=0"),
                                         ({"minAvailable": "0%"}, "minAvailable=0%")])
def test_pdb_without_protection_counts_as_no_pdb(spec, shown):
    [f] = colocated({"deployments": [selected_workload()], "poddisruptionbudgets": [pdb_for(**spec)],
                     "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a")]})
    assert f"web-pdb({shown})" in f.message
    assert "PDB를 maxUnavailable: 1" in f.hint


def test_one_protective_pdb_among_several_is_enough():
    pdbs = [pdb_for(maxUnavailable="100%"), {**pdb_for(maxUnavailable=1), "metadata": {"name": "strict", "namespace": "app"}}]
    assert colocated({"deployments": [selected_workload()], "poddisruptionbudgets": pdbs,
                      "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a")]}) == []


def test_pdb_in_other_namespace_or_for_other_app_does_not_protect():
    pdbs = [pdb_for(ns="other", maxUnavailable=1), pdb_for(app="api", maxUnavailable=1)]
    assert len(colocated({"deployments": [selected_workload()], "poddisruptionbudgets": pdbs,
                          "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a")]})) == 1


def test_unreadable_pdb_values_are_treated_as_protective():
    # 해석할 수 없는 값은 추측으로 검출하지 않는다
    assert colocated({"deployments": [selected_workload()], "poddisruptionbudgets": [pdb_for(maxUnavailable="abc")],
                      "pods": [running_pod("web-1", "node-a"), running_pod("web-2", "node-a")]}) == []


def test_colocated_statefulset_and_system_namespace():
    sts = selected_workload(name="db")
    dns = selected_workload(name="coredns", ns="kube-system")
    snap = Snapshot({"statefulsets": [sts], "deployments": [dns],
                     "pods": [running_pod("db-0", "node-a", app="db"), running_pod("db-1", "node-a", app="db"),
                              running_pod("dns-1", "node-a", app="coredns", ns="kube-system"),
                              running_pod("dns-2", "node-a", app="coredns", ns="kube-system")]})
    assert [f.ref for f in check_colocated_replicas(snap, CTX)] == ["StatefulSet/app/db"]
    ctx = Context(target_version="1.33", include_system=True)
    assert sorted(f.ref for f in check_colocated_replicas(snap, ctx)) == [
        "Deployment/kube-system/coredns", "StatefulSet/app/db"]


def test_selector_matches_in_preflight():
    assert selector_matches({"matchLabels": {"app": "a"}}, {"app": "a", "x": "y"})
    assert not selector_matches({"matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["web"]}]},
                                {"tier": "web"})
