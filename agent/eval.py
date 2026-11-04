"""평가: 시나리오 × 반복 × 모드로 돌려 정답 원인 ID와 비교한다 (자동 채점)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Optional

from .loop import Analysis


@dataclass
class Scenario:
    id: str
    name: str
    alert: str
    expected: str


def load_scenarios(path: Path) -> list[Scenario]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Scenario(s["id"], s["name"], s["alert"], s["expected"]) for s in data]


@dataclass
class Run:
    scenario: str
    mode: str
    repeat: int
    model: str
    expected: str
    top_cause: Optional[str]
    correct: bool
    duration_s: float
    agent_tool_calls: int
    total_tool_calls: int
    llm_calls: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cache_read_tokens: Optional[int]
    cost_usd: Optional[float]
    error: str = ""
    input_total_tokens: Optional[int] = None   # 입력 + 캐시 읽기 + 캐시 쓰기 (claude -p는 캐시를 쓰므로 입력만으로는 작게 보인다)


def score(s: Scenario, mode: str, repeat: int, model: str, a: Analysis) -> Run:
    t = a.totals()
    parts = (t["input_tokens"], t["cache_read_tokens"], t["cache_creation_tokens"])
    input_total = sum(parts) if all(v is not None for v in parts) else None
    return Run(s.id, mode, repeat, model, s.expected, a.top_cause, a.top_cause == s.expected and not a.error,
               a.duration_s, a.agent_tool_calls, len(a.observations), t["llm_calls"], t["input_tokens"],
               t["output_tokens"], t["cache_read_tokens"], t["cost_usd"], a.error, input_total)


def _avg(vals, ndigits: int = 2):
    vals = [v for v in vals if v is not None]
    return round(mean(vals), ndigits) if vals else None


def aggregate(runs: list[Run], keys=("model", "mode", "scenario")) -> list[dict]:
    groups: dict[tuple, list[Run]] = {}
    for r in runs:
        groups.setdefault(tuple(getattr(r, k) for k in keys), []).append(r)
    rows = []
    for key, rs in groups.items():
        rows.append({**dict(zip(keys, key)), "runs": len(rs), "correct": sum(r.correct for r in rs),
                     "accuracy": round(sum(r.correct for r in rs) / len(rs), 2),
                     "avg_seconds": _avg(r.duration_s for r in rs),
                     "avg_agent_tool_calls": _avg(r.agent_tool_calls for r in rs),
                     "avg_total_tool_calls": _avg(r.total_tool_calls for r in rs),
                     "avg_llm_calls": _avg(r.llm_calls for r in rs),
                     "avg_input_tokens": _avg(r.input_tokens for r in rs),
                     "avg_output_tokens": _avg(r.output_tokens for r in rs),
                     "avg_cache_read_tokens": _avg(r.cache_read_tokens for r in rs),
                     "avg_input_total_tokens": _avg(r.input_total_tokens for r in rs),
                     "avg_cost_usd": _avg((r.cost_usd for r in rs), 4),
                     "answers": [r.top_cause or f"(오류) {r.error[:40]}" for r in rs]})
    return rows


def _cell(v) -> str:
    return "-" if v is None else str(v)


def summary_markdown(runs: list[Run], scenarios: list[Scenario]) -> str:
    names = {s.id: s.name for s in scenarios}
    lines = ["# 알림 1차 분석 평가", "",
             "정답: 리포트의 1순위 원인 ID가 시나리오의 정답 원인 ID와 같으면 맞음(오류로 끝난 실행은 틀림).",
             "토큰·비용은 claude -p가 보고한 값. 입력 토큰은 입력 + 캐시 읽기 + 캐시 쓰기를 더한 값이다.", "",
             "## 모드별 합계", "",
             "| 모델 | 모드 | 정확도 | 평균 시간(초) | 평균 도구 호출(LLM 선택) | 평균 도구 호출(전체) | 평균 LLM 호출 | 평균 입력 토큰 | 평균 출력 토큰 | 평균 비용(USD) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(aggregate(runs, ("model", "mode")), key=lambda x: (x["model"], x["mode"])):
        lines.append(f"| {r['model']} | {r['mode'].upper()} | {r['correct']}/{r['runs']} | {_cell(r['avg_seconds'])} | "
                     f"{_cell(r['avg_agent_tool_calls'])} | {_cell(r['avg_total_tool_calls'])} | {_cell(r['avg_llm_calls'])} | "
                     f"{_cell(r['avg_input_total_tokens'])} | {_cell(r['avg_output_tokens'])} | {_cell(r['avg_cost_usd'])} |")
    lines += ["", "## 시나리오별", "",
              "| 모델 | 모드 | 시나리오 | 정답 | 맞춤 | 1순위 답 | 평균 시간(초) | 평균 도구 호출(LLM 선택) | 평균 비용(USD) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    expected = {s.id: s.expected for s in scenarios}
    for r in sorted(aggregate(runs), key=lambda x: (x["model"], x["mode"], x["scenario"])):
        lines.append(f"| {r['model']} | {r['mode'].upper()} | {r['scenario']} {names.get(r['scenario'], '')} | "
                     f"`{expected.get(r['scenario'])}` | {r['correct']}/{r['runs']} | {', '.join(r['answers'])} | "
                     f"{_cell(r['avg_seconds'])} | {_cell(r['avg_agent_tool_calls'])} | {_cell(r['avg_cost_usd'])} |")
    return "\n".join(lines) + "\n"


def load_runs(path: Path) -> list[Run]:
    return [Run(**r) for r in json.loads(path.read_text(encoding="utf-8"))]
