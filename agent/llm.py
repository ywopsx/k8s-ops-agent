"""LLM 백엔드. 에이전트 루프는 Backend 인터페이스만 보고, 실제 호출 방식은 여기서 바꾼다.

지금은 Claude Code의 비대화형 모드(`claude -p`)를 쓴다. 나중에 Anthropic API 백엔드를 같은 인터페이스로 추가한다.

`claude -p`에서 Claude Code의 내장 도구(Bash, 파일 읽기·쓰기 등)는 쓸 수 없게 막는다.
LLM은 다음 행동(도구 이름과 인자, 또는 결론)을 텍스트(JSON)로만 답하고, 도구 실행은 에이전트 코드가 MCP로 한다.
  --tools ""                내장 도구를 모두 끈다 (claude --help: 'Use "" to disable all tools')
  --strict-mcp-config       --mcp-config로 준 MCP 서버만 쓴다. 주지 않으므로 MCP 서버도 없다
  --setting-sources ""      사용자·프로젝트 설정(hooks, 권한, MCP 설정)을 읽지 않는다
  --system-prompt           Claude Code 기본 시스템 프롬프트를 에이전트 프롬프트로 바꾼다
  cwd = 빈 임시 디렉터리     프로젝트 CLAUDE.md를 읽지 않게 한다
호출할 때마다 stream-json의 init 이벤트에서 tools·mcp_servers가 비어 있는지 확인하고, 아니면 결과를 버리고 멈춘다.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol


@dataclass
class LLMResult:
    text: str
    model: str = ""
    duration_s: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    raw_usage: dict = field(default_factory=dict)


class Backend(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> LLMResult: ...


class LLMError(RuntimeError):
    pass


class ToolsNotDisabledError(LLMError):
    """claude -p 세션에 내장 도구나 MCP 서버가 살아 있음."""


# 내장 도구와 외부 설정을 끄는 인자. 테스트에서 그대로 확인한다.
BLOCK_ARGS = ["--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]


class ClaudeCLIBackend:
    name = "claude-cli"

    def __init__(self, model: Optional[str] = None, claude: str = "claude", timeout: float = 300,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.model = model
        self.claude = claude
        self.timeout = timeout
        self._run = run

    def command(self, system: str) -> list[str]:
        cmd = [self.claude, "-p", *BLOCK_ARGS, "--output-format", "stream-json", "--verbose",
               "--system-prompt", system]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def complete(self, system: str, prompt: str) -> LLMResult:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="ops-agent-llm-") as cwd:
            try:
                proc = self._run(self.command(system), input=prompt, capture_output=True, text=True,
                                 timeout=self.timeout, cwd=cwd)
            except subprocess.TimeoutExpired as e:
                raise LLMError(f"claude -p가 {self.timeout:.0f}초 안에 끝나지 않았습니다.") from e
        elapsed = time.monotonic() - started
        return parse_stream_json(proc.stdout, proc.returncode, proc.stderr, elapsed)


def parse_stream_json(stdout: str, returncode: int = 0, stderr: str = "", elapsed: float = 0.0) -> LLMResult:
    init, result = None, None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            init = event
        elif event.get("type") == "result":
            result = event
    if init is None:
        tail = (stderr or stdout).strip().splitlines()[-1:] or [""]
        raise LLMError(f"claude -p의 init 이벤트가 없습니다 (종료 코드 {returncode}): {tail[0][:300]}")
    tools, servers = init.get("tools"), init.get("mcp_servers")
    if tools != [] or servers != []:
        raise ToolsNotDisabledError(f"claude -p 세션에 도구가 남아 있습니다: tools={tools}, mcp_servers={servers}. "
                                    "결과를 쓰지 않고 멈춥니다.")
    if result is None:
        raise LLMError(f"claude -p의 result 이벤트가 없습니다 (종료 코드 {returncode}).")
    if result.get("is_error"):
        raise LLMError(f"claude -p 오류: {str(result.get('result'))[:300]}")
    usage = result.get("usage") or {}
    models = list((result.get("modelUsage") or {}).keys())
    return LLMResult(
        text=result.get("result") or "",
        model=",".join(models) or init.get("model", ""),
        duration_s=round(elapsed or (result.get("duration_ms") or 0) / 1000, 2),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cache_read_tokens=usage.get("cache_read_input_tokens"),
        cache_creation_tokens=usage.get("cache_creation_input_tokens"),
        cost_usd=result.get("total_cost_usd"),
        raw_usage=usage,
    )
