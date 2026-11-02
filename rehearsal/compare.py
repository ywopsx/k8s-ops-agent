"""preflight 점검의 예측과 drain 실측 결과를 워크로드 단위로 맞춰 본다."""
from __future__ import annotations

from dataclasses import dataclass, field

from preflight.checks import (
    SYSTEM_NAMESPACES, Context, check_nodegroup_pinned, check_pdb_blocks_drain, check_single_replica,
    check_topology_spread, check_unmanaged_pods, run_all,
)
from preflight.models import Finding, Severity, Snapshot

from .drain import BLOCKED_PDB, REPLACE_FAILED, SKIPPED, UNMANAGED, PodOutcome

# drain과 관련된 점검만 돌린다. 모두 대상 버전과 무관한 점검이다.
DRAIN_CHECKS = [check_pdb_blocks_drain, check_unmanaged_pods, check_nodegroup_pinned,
                check_topology_spread, check_single_replica]
_VERSION_UNUSED = "0.0"  # DRAIN_CHECKS는 대상 버전을 보지 않는다

# 문제 종류
P_PDB = "PDB에 막힘"
P_UNMANAGED = "컨트롤러 없음"
P_REPLACE = "재배치 실패"
P_DOWNTIME = "다운타임 가능"

# 점검이 예측하는 문제 (MEDIUM 이상만. topology-spread INFO는 예측으로 보지 않는다)
CHECK_PREDICTS = {
    "pdb-blocks-drain": P_PDB,
    "unmanaged-pod": P_UNMANAGED,
    "nodegroup-pinned": P_REPLACE,
    "topology-spread": P_REPLACE,
    "single-replica": P_DOWNTIME,
}

HIT, MISS, UNPREDICTED = "예측함·발생", "예측함·발생 안 함", "예측 못 함·발생"


def predict(snap: Snapshot, include_system: bool = False) -> list[Finding]:
    return run_all(snap, Context(target_version=_VERSION_UNUSED, include_system=include_system), DRAIN_CHECKS)


def actual_problems(p: PodOutcome) -> set[str]:
    found = set()
    if p.outcome == BLOCKED_PDB:
        found.add(P_PDB)
    if p.outcome == UNMANAGED:
        found.add(P_UNMANAGED)
    if p.outcome == REPLACE_FAILED:
        found.add(P_REPLACE)
    if p.downtime:
        found.add(P_DOWNTIME)
    return found


def selector_matches(selector: dict, labels: dict) -> bool:
    """LabelSelector(matchLabels, matchExpressions)가 labels와 맞는지. 빈 selector는 모두와 맞는다."""
    for k, v in (selector.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for e in selector.get("matchExpressions") or []:
        key, op, values = e.get("key"), e.get("operator"), e.get("values") or []
        if op == "In" and labels.get(key) not in values:
            return False
        if op == "NotIn" and key in labels and labels[key] in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True


@dataclass
class Row:
    workload: str
    problem: str
    checks: list = field(default_factory=list)   # 이 문제를 예측한 점검
    occurred: bool = False
    verdict: str = ""


def compare(pods: list[PodOutcome], findings: list[Finding], snap: Snapshot,
            include_system: bool = False) -> list[Row]:
    pdbs = {(p.get("metadata", {}).get("namespace"), p.get("metadata", {}).get("name")): p
            for p in snap.items("poddisruptionbudgets")}

    def finding_covers(f: Finding, pod: PodOutcome) -> bool:
        if f.ref in (pod.workload, pod.ref):
            return True
        if f.kind == "PodDisruptionBudget" and f.namespace == pod.namespace:
            pdb = pdbs.get((f.namespace, f.name))
            return pdb is not None and selector_matches(pdb.get("spec", {}).get("selector") or {}, pod.labels)
        return False

    predicted: dict[tuple, set] = {}   # (workload, problem) -> 점검 이름들
    occurred: set = set()
    order: list[str] = []
    for pod in pods:
        if pod.outcome == SKIPPED or (not include_system and pod.namespace in SYSTEM_NAMESPACES):
            continue
        if pod.workload not in order:
            order.append(pod.workload)
        for f in findings:
            if f.severity >= Severity.MEDIUM and f.check in CHECK_PREDICTS and finding_covers(f, pod):
                predicted.setdefault((pod.workload, CHECK_PREDICTS[f.check]), set()).add(f.check)
        for problem in actual_problems(pod):
            occurred.add((pod.workload, problem))

    rows = []
    problems = list(CHECK_PREDICTS.values())
    for workload in order:
        for problem in dict.fromkeys(problems):
            key = (workload, problem)
            if key not in predicted and key not in occurred:
                continue
            hit = key in occurred
            verdict = (HIT if hit else MISS) if key in predicted else UNPREDICTED
            rows.append(Row(workload=workload, problem=problem, checks=sorted(predicted.get(key, set())),
                            occurred=hit, verdict=verdict))
    return rows
