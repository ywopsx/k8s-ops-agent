from __future__ import annotations

import json
from dataclasses import asdict

from .compare import Row
from .drain import BLOCKED_PDB, OUTCOME_ORDER, DrainResult

EKS_UPDATE_DOC = "https://docs.aws.amazon.com/eks/latest/userguide/managed-node-update-behavior.html"

PDB_EXPLANATION = (
    "EKS 관리형 노드그룹 업그레이드는 노드의 Pod가 **15분** 안에 빠져나가지 않으면(force 플래그 없이) "
    "`PodEvictionFailure`로 실패합니다. 공식 문서가 꼽는 원인은 지나치게 엄격한 PDB와, "
    "한 Pod를 가리키는 PDB가 여러 개인 경우입니다. 위 표에서 'PDB에 막힘'인 Pod는 이 리허설의 타임아웃({timeout:g}초) 동안 "
    "한 번도 evict되지 않았습니다. replica 1 + minAvailable 1처럼 PDB 조건이 스스로 풀리지 않는 구성이라면, "
    "실제 업그레이드에서도 15분 뒤 같은 지점에서 멈춥니다. "
    f"(출처: Amazon EKS 사용자 가이드, Understand each phase of node updates — {EKS_UPDATE_DOC})"
)


def _sec(v) -> str:
    return "-" if v is None else f"{v:g}초"


def to_markdown(result: DrainResult, rows: list[Row]) -> str:
    counts = " · ".join(f"{o} {result.count(o)}" for o in OUTCOME_ORDER)
    lines = [
        f"# drain 검증 결과 — 노드 `{result.node}`",
        "",
        f"- 컨텍스트: `{result.context}`",
        f"- 시작: {result.started_at} · 전체 소요: {result.duration:g}초 · 타임아웃: {result.timeout:g}초",
        f"- 결과: {counts}",
        f"- 노드 상태: {'uncordon 함' if result.uncordoned else 'cordon 상태로 남음 (직접 uncordon 필요)'}",
        "",
        "## Pod별 결과",
        "",
        "| 결과 | Pod | 워크로드 | evict 완료 (drain 시작 기준) | 대체 Pod Ready까지 | 다운타임 가능 | 비고 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in result.pods:
        lines.append(f"| {p.outcome} | `{p.ref}` | `{p.workload}` | {_sec(p.evicted_at)} | {_sec(p.replaced_after)} "
                     f"| {'예' if p.downtime else ''} | {p.note} |")
    lines += ["", "다운타임 가능: evict 시점에 같은 워크로드의 다른 Ready Pod가 없었음."]

    if result.count(BLOCKED_PDB):
        lines += ["", "## PDB에 막힘", "", PDB_EXPLANATION.format(timeout=result.timeout)]

    lines += ["", "## 예측(preflight)과 실측 비교", ""]
    if rows:
        lines += ["| 워크로드 | 문제 | 예측한 점검 | 실제 발생 | 판정 |", "| --- | --- | --- | --- | --- |"]
        for r in rows:
            lines.append(f"| `{r.workload}` | {r.problem} | {', '.join(r.checks) or '-'} "
                         f"| {'예' if r.occurred else '아니오'} | {r.verdict} |")
    else:
        lines.append("예측된 문제도, 실제로 생긴 문제도 없습니다.")
    return "\n".join(lines) + "\n"


def to_json(result: DrainResult, rows: list[Row]) -> str:
    data = asdict(result)
    data["comparison"] = [asdict(r) for r in rows]
    return json.dumps(data, ensure_ascii=False, indent=2)
