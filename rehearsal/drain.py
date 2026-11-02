"""노드를 실제로 cordon하고 Pod를 evict해서, Pod별 결과와 걸린 시간을 기록한다.

kind 클러스터에서만 쓴다(guard.resolve_context를 먼저 통과해야 한다).
--force에 해당하는 동작(단독 Pod 삭제, PDB 무시)은 하지 않는다.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .kube import ERROR, EVICTED, GONE, PDB_MULTIPLE, EvictResult, Kube, KubectlError

REPLACED = "재배치 완료"
REPLACE_FAILED = "재배치 실패"
BLOCKED_PDB = "PDB에 막힘"
UNMANAGED = "컨트롤러 없음"
EVICT_ERROR = "evict 실패"
SKIPPED = "건너뜀"
# 리포트 정렬 순서 (문제가 큰 것부터)
OUTCOME_ORDER = [BLOCKED_PDB, REPLACE_FAILED, UNMANAGED, EVICT_ERROR, REPLACED, SKIPPED]

MIRROR_ANNOTATION = "kubernetes.io/config.mirror"


@dataclass
class PodOutcome:
    namespace: str
    name: str
    workload: str                   # preflight Finding.ref와 같은 형식 (예: Deployment/app/web)
    labels: dict = field(default_factory=dict)
    outcome: str = ""
    note: str = ""
    attempts: int = 0               # eviction 요청 횟수
    evicted_at: Optional[float] = None      # drain 시작부터 evict 성공까지(초)
    replaced_after: Optional[float] = None  # evict 성공부터 대체 Pod Ready까지(초)
    downtime: bool = False          # evict 시점에 같은 워크로드의 다른 Ready Pod가 없었음

    @property
    def ref(self) -> str:
        return f"Pod/{self.namespace}/{self.name}"


@dataclass
class DrainResult:
    node: str
    context: str
    timeout: float
    started_at: str = ""
    duration: float = 0.0
    uncordoned: bool = True
    pods: list = field(default_factory=list)

    def count(self, outcome: str) -> int:
        return sum(1 for p in self.pods if p.outcome == outcome)

    @property
    def ok(self) -> bool:
        return all(p.outcome in (REPLACED, SKIPPED) for p in self.pods)


# ---------------------------------------------------------------------------
# Pod 정보 읽기
# ---------------------------------------------------------------------------
def controller_of(obj: Optional[dict]) -> Optional[dict]:
    refs = (obj or {}).get("metadata", {}).get("ownerReferences") or []
    return next((r for r in refs if r.get("controller")), refs[0] if refs else None)


def _uid(obj: dict) -> str:
    return obj.get("metadata", {}).get("uid", "")


def _owner_uid(pod: dict) -> str:
    owner = controller_of(pod)
    return owner.get("uid", "") if owner else ""


def skip_reason(pod: dict) -> Optional[str]:
    md = pod.get("metadata", {})
    if MIRROR_ANNOTATION in md.get("annotations", {}):
        return "mirror Pod (kubelet이 관리)"
    owner = controller_of(pod)
    if owner and owner.get("kind") == "DaemonSet":
        return "DaemonSet Pod (drain 대상 아님)"
    if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
        return "이미 종료된 Pod"
    return None


def is_ready(pod: dict) -> bool:
    if pod.get("metadata", {}).get("deletionTimestamp"):
        return False
    return any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in pod.get("status", {}).get("conditions", []))


def schedule_problem(pod: dict) -> str:
    for c in pod.get("status", {}).get("conditions", []):
        if c.get("type") == "PodScheduled" and c.get("status") == "False":
            return c.get("message") or c.get("reason", "")
    return ""


def workload_ref(kube: Kube, pod: dict, cache: dict) -> str:
    md = pod.get("metadata", {})
    ns, name = md.get("namespace", ""), md.get("name", "")
    owner = controller_of(pod)
    if owner is None:
        return f"Pod/{ns}/{name}"
    kind, oname = owner.get("kind", ""), owner.get("name", "")
    if kind == "ReplicaSet":
        key = (ns, oname)
        if key not in cache:
            parent = controller_of(kube.get("replicaset", oname, ns))
            cache[key] = f"{parent['kind']}/{ns}/{parent['name']}" if parent else f"ReplicaSet/{ns}/{oname}"
        return cache[key]
    return f"{kind}/{ns}/{oname}"


# ---------------------------------------------------------------------------
# drain
# ---------------------------------------------------------------------------
@dataclass
class _Target:
    pod: dict
    out: PodOutcome
    uid: str
    owner_uid: str
    last: Optional[EvictResult] = None
    t_evicted: Optional[float] = None
    replacement: Optional[str] = None


def drain_node(kube: Kube, node: str, timeout: float = 120.0, interval: float = 2.0, keep_cordoned: bool = False,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep) -> DrainResult:
    """cordon → Pod 분류 → eviction 반복 + 대체 Pod 대기 → uncordon(항상, --keep-cordoned 제외).

    eviction과 대체 Pod 대기는 하나의 타임아웃(timeout초) 안에서 함께 진행한다.
    """
    result = DrainResult(node=node, context=kube.context, timeout=timeout)
    start = clock()
    kube.cordon(node)
    try:
        targets = _prepare(kube, kube.pods_on_node(node), result)
        _evict_and_watch(kube, targets, start, start + timeout, interval, clock, sleep)
    finally:
        if keep_cordoned:
            result.uncordoned = False
        else:
            try:
                kube.uncordon(node)
            except KubectlError as e:
                result.uncordoned = False
                print(f"[warn] uncordon 실패, 직접 확인하세요: {e}", file=sys.stderr)
        result.duration = round(clock() - start, 1)
    result.pods.sort(key=lambda p: (OUTCOME_ORDER.index(p.outcome) if p.outcome in OUTCOME_ORDER else 99, p.ref))
    return result


def _prepare(kube: Kube, pods: list[dict], result: DrainResult) -> list[_Target]:
    cache: dict = {}
    targets = []
    for pod in pods:
        md = pod.get("metadata", {})
        out = PodOutcome(namespace=md.get("namespace", ""), name=md.get("name", ""),
                         workload=workload_ref(kube, pod, cache), labels=dict(md.get("labels", {})))
        result.pods.append(out)
        reason = skip_reason(pod)
        if reason:
            out.outcome, out.note = SKIPPED, reason
            continue
        if controller_of(pod) is None:
            out.outcome = UNMANAGED
            out.note = "컨트롤러가 없어 evict하지 않음 (--force에 해당하는 삭제는 하지 않는다)"
            continue
        targets.append(_Target(pod=pod, out=out, uid=_uid(pod), owner_uid=_owner_uid(pod)))
    return targets


def _evict_and_watch(kube: Kube, targets: list[_Target], start: float, deadline: float, interval: float,
                     clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
    # drain 전에 있던 Pod. 이 목록에 없는 같은 컨트롤러의 Pod를 대체 Pod로 본다(StatefulSet은 이름이 같아 uid로 구분).
    before: dict[str, set] = {}
    for ns in sorted({t.out.namespace for t in targets}):
        for p in kube.pods_in_namespace(ns):
            before.setdefault(_owner_uid(p), set()).add(_uid(p))

    pending = list(targets)          # 아직 evict되지 않음
    waiting: list[_Target] = []      # evict됨, 대체 Pod 대기
    evicted: set = set()
    used: set = set()                # 이미 다른 evict Pod의 대체로 짝지은 Pod

    while True:
        cache: dict = {}

        def pods_of(ns: str) -> list[dict]:
            if ns not in cache:
                cache[ns] = kube.pods_in_namespace(ns)
            return cache[ns]

        for t in list(pending):
            others = [p for p in pods_of(t.out.namespace)
                      if _owner_uid(p) == t.owner_uid and _uid(p) != t.uid and _uid(p) not in evicted and is_ready(p)]
            t.last = kube.evict(t.out.namespace, t.out.name)
            t.out.attempts += 1
            if t.last.status in (EVICTED, GONE):
                t.t_evicted = clock()
                t.out.evicted_at = round(t.t_evicted - start, 1)
                t.out.downtime = not others
                evicted.add(t.uid)
                pending.remove(t)
                waiting.append(t)
            elif t.last.status == ERROR:
                t.out.outcome, t.out.note = EVICT_ERROR, t.last.message
                pending.remove(t)
            # PDB, PDB_MULTIPLE은 타임아웃까지 다시 시도한다 (kubectl drain과 같은 동작)

        cache.clear()  # evict 이후 상태로 다시 조회
        for t in waiting:
            if t.replacement:
                continue
            new = [p for p in pods_of(t.out.namespace)
                   if _owner_uid(p) == t.owner_uid and _uid(p) not in before.get(t.owner_uid, set())
                   and _uid(p) not in used]
            ready = [p for p in new if is_ready(p)]
            if ready:
                t.replacement = _uid(ready[0])
                used.add(t.replacement)
                t.out.outcome = REPLACED
                t.out.replaced_after = round(clock() - t.t_evicted, 1)
                rmd = ready[0].get("metadata", {})
                t.out.note = f"대체 Pod {rmd.get('name', '')} ({ready[0].get('spec', {}).get('nodeName', '?')})"
            else:
                problems = [m for m in (schedule_problem(p) for p in new) if m]
                t.out.note = problems[0] if problems else ""

        if not pending and all(t.replacement for t in waiting):
            break
        if clock() >= deadline:
            break
        sleep(interval)

    for t in pending:
        t.out.outcome = BLOCKED_PDB
        reason = ("한 Pod에 PDB가 여러 개라 eviction API가 거부함(500)" if t.last and t.last.status == PDB_MULTIPLE
                  else "PDB가 중단을 허용하지 않음(429)")
        t.out.note = f"{reason}, 타임아웃까지 {t.out.attempts}회 시도"
    for t in waiting:
        if not t.replacement:
            t.out.outcome = REPLACE_FAILED
            t.out.note = (f"대체 Pod 스케줄 실패: {t.out.note}" if t.out.note
                          else "타임아웃까지 대체 Pod가 Ready가 되지 않음")
