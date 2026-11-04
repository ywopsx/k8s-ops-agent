"""분석 결과 리포트 (Markdown, JSON)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .loop import MODE_FIXED, Analysis

MODE_NAMES = {"c": "C (Pod·Event 수집 후 LLM이 도구 선택)", "a": "A (고정 수집 + LLM 1회)"}


def _fmt(v) -> str:
    return "-" if v is None else str(v)


def to_markdown(a: Analysis, runbook: Optional[Path] = None) -> str:
    t = a.totals()
    lines = [f"# 알림 1차 분석 — {a.alert.name}", "",
             f"- 대상: namespace `{a.alert.namespace or '-'}`"
             + (f", pod `{a.alert.pod}`" if a.alert.pod else "")
             + (f", service `{a.alert.service}`" if a.alert.service else ""),
             f"- 모드: {MODE_NAMES.get(a.mode, a.mode)}",
             "- 이 리포트는 읽기 전용 조회로 만든 1차 분석입니다. 조치는 사람이 확인한 뒤 결정합니다.", ""]
    if a.error:
        lines += [f"> **분석 실패:** {a.error}", ""]
    if a.summary:
        lines += ["## 결론", "", a.summary, ""]
    if a.causes:
        lines += ["## 원인 후보 (가능성 순)", "", "| 순위 | 원인 ID | 설명 | 확신도 | 근거 |", "| --- | --- | --- | --- | --- |"]
        for i, c in enumerate(a.causes, 1):
            ev = "<br>".join(e.replace("|", "\\|") for e in c.evidence) or "-"
            lines.append(f"| {i} | `{c.id}` | {c.title} | {c.confidence:.2f} | {ev} |")
        lines.append("")
    if a.state_summary:
        lines += ["## 조회한 리소스 상태", ""] + [f"- {s}" for s in a.state_summary] + [""]
    lines += ["## 런북", ""]
    if runbook:
        lines += [f"`runbooks/{runbook.name}`", "", runbook.read_text(encoding="utf-8").strip(), ""]
    else:
        lines += ["가장 가능성 높은 원인에 맞는 런북이 없습니다.", ""]
    if a.commands:
        lines += ["## 확인 명령 (읽기 전용)", "", "```bash"] + a.commands + ["```", ""]
    lines += ["## 조회 기록", "", "| # | 구분 | 도구 | 인자 | 결과 | 이유 |", "| --- | --- | --- | --- | --- | --- |"]
    for i, o in enumerate(a.observations, 1):
        args = json.dumps(o.arguments, ensure_ascii=False, sort_keys=True).replace("|", "\\|")
        status = "오류" if o.is_error else f"{o.chars}자"
        by = "고정 수집" if o.by == "initial" else "LLM 선택"
        lines.append(f"| {i} | {by} | `{o.tool}` | `{args}` | {status} | {o.reason.replace('|', '/') or '-'} |")
    lines += ["", "## 실행 정보", "",
              f"- 백엔드: {a.backend}, 모델: {', '.join(t['models']) or '-'}",
              f"- 전체 시간: {a.duration_s}초 (LLM {t['llm_seconds']}초, 호출 {t['llm_calls']}회)",
              f"- 도구 호출: 고정 수집 {len(a.observations) - a.agent_tool_calls}회, "
              f"LLM 선택 {a.agent_tool_calls}회" + (" (모드 A는 LLM이 도구를 고르지 않음)" if a.mode == MODE_FIXED else ""),
              f"- 토큰: 입력 {_fmt(t['input_tokens'])}, 출력 {_fmt(t['output_tokens'])}, "
              f"캐시 읽기 {_fmt(t['cache_read_tokens'])}, 캐시 쓰기 {_fmt(t['cache_creation_tokens'])}",
              f"- 비용(USD, claude -p 보고값): {_fmt(t['cost_usd'])}"]
    if a.notes:
        lines += ["", "## 참고", ""] + [f"- {n}" for n in a.notes]
    return "\n".join(lines) + "\n"


def to_json(a: Analysis, runbook: Optional[Path] = None) -> str:
    d = a.to_dict()
    d["runbook"] = f"runbooks/{runbook.name}" if runbook else None
    return json.dumps(d, ensure_ascii=False, indent=2)
