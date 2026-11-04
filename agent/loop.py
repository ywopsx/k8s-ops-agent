"""에이전트 루프.

- 모드 C (기본): 처음에 Pod 상태와 Event만 수집해 LLM에 준다. LLM은 근거가 부족하면 읽기 도구를 골라
  추가 조회를 요청하고(최대 max_tool_calls회), 충분하면 결론을 낸다.
- 모드 A (비교용): 정해 둔 조회(Pod, 로그, Event, Service, Endpoints, Deployment)를 모두 한 뒤 LLM을 한 번만 부른다.

LLM은 JSON 텍스트로만 답한다. 도구 실행은 이 코드가 MCP로 하고, 결과는 마스킹한 뒤 LLM에 넘긴다.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .alert import Alert
from .causes import CAUSES, RUNBOOKS
from .llm import Backend, LLMError, LLMResult
from .mask import mask
from .tools import ToolBox, ToolSpec

MODE_AGENT = "c"
MODE_FIXED = "a"
MAX_OUTPUT_CHARS = 6000   # 도구 결과 하나를 LLM에 넘길 때의 최대 길이


@dataclass
class Observation:
    tool: str
    arguments: dict
    text: str              # 마스킹·자른 결과 (LLM에 넘긴 그대로)
    is_error: bool
    by: str                # "initial"(고정 수집) 또는 "agent"(LLM이 고름)
    reason: str = ""
    duration_s: float = 0.0
    chars: int = 0         # 자르기 전 길이


@dataclass
class Cause:
    id: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return CAUSES.get(self.id, self.id)


@dataclass
class Analysis:
    alert: Alert
    mode: str
    backend: str
    causes: list[Cause] = field(default_factory=list)
    summary: str = ""
    state_summary: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    llm_calls: list[LLMResult] = field(default_factory=list)
    duration_s: float = 0.0
    error: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def top_cause(self) -> Optional[str]:
        return self.causes[0].id if self.causes else None

    @property
    def agent_tool_calls(self) -> int:
        return sum(1 for o in self.observations if o.by == "agent")

    def runbook(self, runbooks_dir: Path) -> Optional[Path]:
        name = RUNBOOKS.get(self.top_cause or "")
        path = runbooks_dir / name if name else None
        return path if path and path.exists() else None

    def totals(self) -> dict:
        def total(attr):
            vals = [getattr(c, attr) for c in self.llm_calls]
            return sum(vals) if vals and all(v is not None for v in vals) else None
        return {
            "llm_calls": len(self.llm_calls),
            "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"),
            "cache_read_tokens": total("cache_read_tokens"),
            "cache_creation_tokens": total("cache_creation_tokens"),
            "cost_usd": round(total("cost_usd"), 4) if total("cost_usd") is not None else None,
            "llm_seconds": round(sum(c.duration_s for c in self.llm_calls), 2),
            "models": sorted({c.model for c in self.llm_calls if c.model}),
        }

    def to_dict(self) -> dict:
        d = {
            "alert": asdict(self.alert), "mode": self.mode, "backend": self.backend,
            "top_cause": self.top_cause,
            "causes": [{**asdict(c), "title": c.title} for c in self.causes],
            "summary": self.summary, "state_summary": self.state_summary, "commands": self.commands,
            "observations": [asdict(o) for o in self.observations],
            "agent_tool_calls": self.agent_tool_calls,
            "llm": self.totals(),
            "llm_calls": [{k: v for k, v in asdict(c).items() if k != "text"} for c in self.llm_calls],
            "duration_s": self.duration_s, "error": self.error, "notes": self.notes,
        }
        return d


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------
def system_prompt(runbooks: str, tools: list[ToolSpec], mode: str, max_tool_calls: int) -> str:
    causes = "\n".join(f"- {cid}: {desc}" for cid, desc in CAUSES.items())
    lines = [
        "너는 Kubernetes 운영 알림을 1차 분석하는 SRE 에이전트다. 클러스터를 바꾸지 않는다(읽기 전용).",
        "주어진 알림과 조회 결과만 근거로 원인 후보를 고른다. 조회 결과에 없는 사실을 지어내지 않는다.",
        "",
        "## 답하는 형식",
        "반드시 JSON 객체 하나만 답한다. 앞뒤에 설명이나 코드 블록을 붙이지 않는다.",
    ]
    if mode == MODE_AGENT:
        lines += [
            f"근거가 부족하면 도구 하나를 요청한다(남은 횟수 안에서, 전체 최대 {max_tool_calls}회):",
            '{"action": "tool", "tool": "<도구 이름>", "arguments": {...}, "reason": "<왜 필요한지>"}',
            "근거가 충분하면 결론을 낸다:",
        ]
    else:
        lines += ["추가 조회는 할 수 없다. 주어진 조회 결과로 결론을 낸다:"]
    lines += [
        '{"action": "final", "summary": "<한두 문장 결론>",',
        ' "state_summary": ["<조회한 리소스 상태 요약>", ...],',
        ' "causes": [{"id": "<원인 ID>", "confidence": 0.0~1.0, "evidence": ["<어떤 조회 결과의 무엇을 보고 판단했는지>", ...]}, ...],',
        ' "commands": ["<사람이 바로 실행해 볼 읽기 전용 확인 명령, 예: kubectl -n ns describe pod x>", ...]}',
        "causes는 가능성 높은 순으로 1~3개. id는 아래 목록에서만 고른다. 문장은 한국어로 쓴다.",
        "commands에는 kubectl get/describe/logs처럼 읽기 전용 명령만 넣는다.",
        "",
        "## 원인 ID 목록",
        causes,
    ]
    if mode == MODE_AGENT:
        lines += ["", "## 쓸 수 있는 도구 (모두 읽기 전용)"]
        for t in tools:
            props = (t.parameters or {}).get("properties", {})
            required = set((t.parameters or {}).get("required", []))
            args = ", ".join(f"{k}{'(필수)' if k in required else ''}: {v.get('type', '')}" for k, v in props.items())
            desc = " ".join(t.description.split())[:300]
            lines.append(f"- {t.name}({args}) — {desc}")
    if runbooks:
        lines += ["", "## 런북 (원인을 확인하는 방법과 조치. 참고용)", runbooks]
    return "\n".join(lines)


def user_prompt(alert: Alert, observations: list[Observation], remaining: Optional[int],
                feedback: str = "") -> str:
    parts = ["## 알림", alert.describe(), "", "## 지금까지의 조회 결과"]
    for i, o in enumerate(observations, 1):
        args = json.dumps(o.arguments, ensure_ascii=False, sort_keys=True)
        status = "오류" if o.is_error else "성공"
        parts += [f"### {i}. {o.tool} {args} ({status}, {'고정 수집' if o.by == 'initial' else '요청한 조회'})",
                  o.text or "(빈 결과)", ""]
    if remaining is not None:
        parts.append(f"남은 도구 호출: {remaining}회" + (" — 이제 결론(action=final)만 답한다." if remaining == 0 else ""))
    if feedback:
        parts += ["", feedback]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 응답 해석
# ---------------------------------------------------------------------------
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_action(text: str) -> dict:
    """LLM 답에서 JSON 객체를 꺼낸다. 코드 블록이나 앞뒤 문장이 붙어 있어도 첫 { 부터 마지막 } 까지 읽는다."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 객체가 없습니다.")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict) or data.get("action") not in ("tool", "final"):
        raise ValueError("action이 tool 또는 final이 아닙니다.")
    return data


def to_causes(raw) -> tuple[list[Cause], list[str]]:
    causes, notes = [], []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id", "")).strip()
        if cid not in CAUSES:
            notes.append(f"목록에 없는 원인 ID '{cid}'를 other로 바꿈")
            cid = "other"
        try:
            conf = max(0.0, min(1.0, float(item.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        evidence = [str(e) for e in item.get("evidence", []) if e] if isinstance(item.get("evidence"), list) else []
        causes.append(Cause(cid, conf, evidence))
    causes.sort(key=lambda c: -c.confidence)   # 같은 확신도면 LLM이 적은 순서를 유지
    return causes, notes


def _clip(text: str) -> str:
    text = mask(text)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n...(이후 {len(text) - MAX_OUTPUT_CHARS}자 생략)"


# ---------------------------------------------------------------------------
# 조회 계획
# ---------------------------------------------------------------------------
def initial_calls(alert: Alert) -> list[tuple[str, dict]]:
    """모드 C의 첫 수집: Pod 상태와 Event만."""
    ns = alert.namespace or "default"
    calls = [("pods_list_in_namespace", {"namespace": ns})]
    if alert.pod:
        calls.append(("pods_get", {"namespace": ns, "name": alert.pod}))
    calls.append(("events_list", {"namespace": ns}))
    return calls


def fixed_calls(alert: Alert, log_lines: int) -> list[tuple[str, dict]]:
    """모드 A의 고정 수집: 알림 종류와 상관없이 같은 조회를 모두 한다."""
    ns = alert.namespace or "default"
    calls = initial_calls(alert)
    if alert.pod:
        calls += [("pods_log", {"namespace": ns, "name": alert.pod, "tail": log_lines}),
                  ("pods_log", {"namespace": ns, "name": alert.pod, "tail": log_lines, "previous": True})]
    calls += [("resources_list", {"apiVersion": "v1", "kind": "Service", "namespace": ns}),
              ("resources_list", {"apiVersion": "v1", "kind": "Endpoints", "namespace": ns}),
              ("resources_list", {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": ns})]
    return calls


def _limit_logs(tool: str, arguments: dict, log_lines: int) -> dict:
    """LLM이 고른 로그 조회도 최근 log_lines줄을 넘지 않게 한다."""
    if tool != "pods_log":
        return arguments
    args = dict(arguments)
    try:
        tail = int(args.get("tail") or log_lines)
    except (TypeError, ValueError):
        tail = log_lines
    args["tail"] = max(1, min(tail, log_lines))
    return args


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
async def analyze(alert: Alert, toolbox: ToolBox, backend: Backend, mode: str = MODE_AGENT,
                  runbooks: str = "", max_tool_calls: int = 5, log_lines: int = 50) -> Analysis:
    started = time.monotonic()
    result = Analysis(alert=alert, mode=mode, backend=backend.name)
    specs = toolbox.specs()
    tool_names = {t.name for t in specs}

    async def observe(tool: str, arguments: dict, by: str, reason: str = "") -> None:
        arguments = _limit_logs(tool, arguments, log_lines)
        res = await toolbox.call(tool, arguments)
        result.observations.append(Observation(tool, arguments, _clip(res.text), res.is_error, by, reason,
                                               res.duration_s, len(res.text)))

    plan = fixed_calls(alert, log_lines) if mode == MODE_FIXED else initial_calls(alert)
    for tool, args in plan:
        if tool in tool_names:
            await observe(tool, args, "initial")
        else:
            result.notes.append(f"도구 {tool}이 없어 고정 수집에서 건너뜀")

    system = system_prompt(runbooks, specs, mode, max_tool_calls)
    feedback = ""
    parse_failures = 0
    # 도구를 다 쓴 뒤에도 결론을 내지 않고 도구만 요청하는 경우를 막는 상한
    max_llm_calls = (1 if mode == MODE_FIXED else max_tool_calls + 1) + 2
    try:
        while True:
            if len(result.llm_calls) >= max_llm_calls:
                raise LLMError(f"LLM을 {max_llm_calls}번 불렀지만 결론(action=final)을 내지 않았습니다.")
            remaining = None if mode == MODE_FIXED else max_tool_calls - result.agent_tool_calls
            llm = backend.complete(system, user_prompt(alert, result.observations, remaining, feedback))
            result.llm_calls.append(llm)
            feedback = ""
            try:
                action = parse_action(llm.text)
            except (ValueError, json.JSONDecodeError) as e:
                parse_failures += 1
                if parse_failures > 1:
                    raise LLMError(f"LLM 답을 JSON으로 읽지 못했습니다(2회): {e}")
                feedback = f"직전 답을 JSON으로 읽지 못했다({e}). 형식에 맞는 JSON 객체 하나만 답한다."
                continue
            if action["action"] == "tool":
                tool = str(action.get("tool", ""))
                if mode == MODE_FIXED or remaining == 0:
                    feedback = "더 조회할 수 없다. 지금까지의 결과로 결론(action=final)만 답한다."
                    continue
                if tool not in tool_names:
                    feedback = f"'{tool}'은 쓸 수 있는 도구가 아니다. 목록의 도구만 쓴다."
                    result.notes.append(f"허용되지 않은 도구 요청: {tool}")
                    # 잘못된 요청도 호출 횟수로 센다 (무한 반복 방지)
                    result.observations.append(Observation(tool, action.get("arguments") or {}, "허용되지 않은 도구",
                                                           True, "agent", str(action.get("reason", ""))))
                    continue
                args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
                await observe(tool, args, "agent", str(action.get("reason", "")))
                continue
            result.causes, notes = to_causes(action.get("causes"))
            result.notes += notes
            result.summary = str(action.get("summary", ""))
            result.state_summary = [str(s) for s in action.get("state_summary", []) or []]
            result.commands = [str(c) for c in action.get("commands", []) or []]
            if not result.causes:
                result.error = "LLM이 원인 후보를 내지 않았습니다."
            break
    except LLMError as e:
        result.error = str(e)
    result.duration_s = round(time.monotonic() - started, 2)
    return result


def load_runbooks(runbooks_dir: Path) -> str:
    """런북 Markdown을 모두 이어 붙인다 (시나리오별로 짧게 쓴다)."""
    if not runbooks_dir.is_dir():
        return ""
    parts = []
    for path in sorted(runbooks_dir.glob("*.md")):
        parts.append(f"### {path.name}\n{path.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)
