from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict

from .models import Finding, Severity

CHECK_TITLES = {
    "nodegroup-pinned": "노드그룹 이름에 묶인 스케줄링",
    "pdb-blocks-drain": "drain을 막는 PodDisruptionBudget",
    "unmanaged-pod": "컨트롤러 없는 단독 Pod",
    "single-replica": "replica 1개 워크로드",
    "removed-api": "대상 버전에서 제거된 API",
    "al2-node": "대상 버전에서 쓸 수 없는 AL2 노드",
    "vpc-cni-env": "VPC CNI(aws-node) 설정",
    "lb-target-instance": "instance 타입 로드밸런서 대상",
    "topology-spread": "AZ 분산 제약",
}


def to_markdown(findings: list[Finding], target_version: str) -> str:
    counts = Counter(f.severity for f in findings)
    lines = [
        f"# 업그레이드 사전 점검 결과 (대상 버전 {target_version})",
        "",
        f"HIGH {counts[Severity.HIGH]}건 · MEDIUM {counts[Severity.MEDIUM]}건 · INFO {counts[Severity.INFO]}건",
        "",
    ]
    if not findings:
        lines.append("발견된 항목이 없습니다.")
        return "\n".join(lines)
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(f.check, []).append(f)
    # 가장 심각한 항목이 있는 점검부터, 점검 안에서는 심각도 순으로
    ordered = sorted(groups.items(), key=lambda kv: (-max(f.severity for f in kv[1]), kv[0]))
    for check, items in ordered:
        lines += ["", f"## {CHECK_TITLES.get(check, check)}", "",
                  "| 심각도 | 리소스 | 내용 | 조치 |", "| --- | --- | --- | --- |"]
        for f in sorted(items, key=lambda x: (-x.severity, x.ref)):
            lines.append(f"| {f.severity.name} | `{f.ref}` | {f.message} | {f.hint} |")
    return "\n".join(lines) + "\n"


def to_json(findings: list[Finding]) -> str:
    rows = []
    for f in findings:
        row = asdict(f)
        row["severity"] = f.severity.name
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False, indent=2)
