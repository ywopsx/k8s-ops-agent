"""run_preflight 도구의 본체. MCP SDK 없이 테스트할 수 있게 서버와 나눠 둔다.

preflight는 읽기 전용(`kubectl get`만)이지만, 이 프로젝트 규칙대로 kind 컨텍스트에서만 실행한다(rehearsal.guard).
preflight.collect는 조회 실패를 stdout에 경고로 찍는데, stdio MCP에서는 stdout이 JSON-RPC 통로라
경고를 가로채 결과의 warnings로 돌려준다.
"""
from __future__ import annotations

import contextlib
import io
import json
from typing import Callable, Optional

from preflight import collect
from preflight.checks import Context, run_all
from preflight.models import Severity, Snapshot
from rehearsal.guard import GuardError, resolve_context
from rehearsal.kube import Runner, kubectl_runner


def run_preflight(target_version: str = "1.33", include_system: bool = False,
                  min_severity: str = "MEDIUM", snapshot_dir: Optional[str] = None,
                  runner: Optional[Runner] = None,
                  collector: Callable[..., Snapshot] = collect.from_cluster) -> str:
    """업그레이드·노드 교체 사전 점검을 돌리고 Finding 목록을 JSON 문자열로 돌려준다."""
    try:
        threshold = Severity[min_severity.upper()]
    except KeyError:
        return json.dumps({"error": f"min_severity는 INFO, MEDIUM, HIGH 중 하나입니다: {min_severity}"}, ensure_ascii=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        if snapshot_dir:
            snap = collect.from_dir(snapshot_dir)
            context = None
        else:
            try:
                context = resolve_context(runner or kubectl_runner())
            except GuardError as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)
            snap = collector(context=context)
        findings = run_all(snap, Context(target_version=target_version, include_system=include_system))
    rows = [{"check": f.check, "severity": f.severity.name, "ref": f.ref, "message": f.message, "hint": f.hint}
            for f in findings if f.severity >= threshold]
    warnings = [line.strip() for line in out.getvalue().splitlines() if line.strip()]
    return json.dumps({"context": context, "target_version": target_version, "findings": rows,
                       "omitted_below_threshold": len(findings) - len(rows), "warnings": warnings},
                      ensure_ascii=False, indent=1)
