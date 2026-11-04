"""에이전트 테스트용 가짜 LLM 백엔드와 가짜 MCP 도구 상자. 실제 LLM·클러스터를 부르지 않는다."""
from __future__ import annotations

import json

from agent.alert import Alert
from agent.llm import LLMResult
from agent.tools import ToolResult, ToolSpec


class FakeBackend:
    name = "fake"

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> LLMResult:
        self.prompts.append((system, prompt))
        reply = self.replies.pop(0) if self.replies else final("other")
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LLMResult(text=text, model="fake-model", duration_s=0.1, input_tokens=100, output_tokens=20,
                         cache_read_tokens=0, cache_creation_tokens=0, cost_usd=0.001)


class FakeToolBox:
    def __init__(self, outputs: dict | None = None,
                 names=("pods_list_in_namespace", "pods_get", "pods_log", "events_list", "resources_list",
                        "resources_get", "run_preflight")):
        self.outputs = outputs or {}
        self.names = names
        self.calls: list[tuple[str, dict]] = []

    def specs(self):
        return [ToolSpec(n, f"{n} 설명", {"type": "object", "properties": {"namespace": {"type": "string"}}})
                for n in self.names]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return ToolResult(self.outputs.get(name, f"{name} 결과"), is_error=False, duration_s=0.01)


def tool(tool_name, /, **arguments):
    return {"action": "tool", "tool": tool_name, "arguments": arguments, "reason": "확인"}


def final(*cause_ids, confidence=(0.9, 0.3, 0.1)):
    return {"action": "final", "summary": "결론", "state_summary": ["상태"],
            "causes": [{"id": c, "confidence": confidence[i], "evidence": [f"{c} 근거"]} for i, c in enumerate(cause_ids)],
            "commands": ["kubectl -n shop describe pod x"]}


POD_ALERT = Alert(name="KubePodCrashLooping", namespace="shop", pod="report-worker-abc",
                  labels={"alertname": "KubePodCrashLooping", "namespace": "shop", "pod": "report-worker-abc"})
SVC_ALERT = Alert(name="ProbeFailed", namespace="shop", service="checkout-api",
                  labels={"alertname": "ProbeFailed", "namespace": "shop", "service": "checkout-api"})
