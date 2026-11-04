"""MCP 도구 상자. 에이전트는 MCP 클라이언트이고, 붙인 서버의 도구 중 허용 목록에 있는 것만 LLM에 보여 준다.

권한은 세 겹으로 막는다.
1. MCP 서버: kubernetes-mcp-server를 read_only = true로 실행한다 (쓰기 도구가 목록에서 빠진다).
2. kubeconfig: 기본 view ClusterRole만 가진 ServiceAccount 토큰. Secret은 읽지 못한다.
3. 컨텍스트: kind-로 시작하는 컨텍스트만 허용한다 (rehearsal.guard 재사용, cli.py에서 확인).
여기에 더해, 아래 허용 목록에 없는 도구는 서버가 내놓아도 쓰지 않는다.
"""
from __future__ import annotations

import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Optional, Protocol

# 서버 이름 -> LLM에 보여 줄 읽기 도구
ALLOWED_TOOLS: dict[str, set[str]] = {
    "kubernetes": {"pods_list_in_namespace", "pods_get", "pods_log", "events_list",
                   "resources_get", "resources_list", "namespaces_list"},
    "preflight": {"run_preflight"},
}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    server: str = ""


@dataclass
class ToolResult:
    text: str
    is_error: bool = False
    duration_s: float = 0.0


class ToolBox(Protocol):
    def specs(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict) -> ToolResult: ...


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: Optional[dict] = None


class MCPToolBox:
    """stdio MCP 서버 여러 개에 붙는다. `async with MCPToolBox(servers) as box:`로 쓴다."""

    def __init__(self, servers: list[ServerSpec], allowed: dict[str, set[str]] = ALLOWED_TOOLS):
        self.servers = servers
        self.allowed = allowed
        self._stack = AsyncExitStack()
        self._sessions: dict[str, object] = {}   # 도구 이름 -> ClientSession
        self._specs: list[ToolSpec] = []
        self.hidden: dict[str, list[str]] = {}   # 서버가 내놓았지만 허용 목록에 없어 숨긴 도구

    async def __aenter__(self) -> "MCPToolBox":
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        await self._stack.__aenter__()
        try:
            for spec in self.servers:
                params = StdioServerParameters(command=spec.command, args=spec.args, env=spec.env)
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                allowed = self.allowed.get(spec.name, set())
                for tool in (await session.list_tools()).tools:
                    if tool.name not in allowed:
                        self.hidden.setdefault(spec.name, []).append(tool.name)
                        continue
                    self._sessions[tool.name] = session
                    self._specs.append(ToolSpec(tool.name, tool.description or "", tool.inputSchema or {}, spec.name))
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    def specs(self) -> list[ToolSpec]:
        return list(self._specs)

    async def call(self, name: str, arguments: dict) -> ToolResult:
        session = self._sessions.get(name)
        if session is None:
            return ToolResult(f"허용되지 않은 도구입니다: {name}", is_error=True)
        started = time.monotonic()
        try:
            res = await session.call_tool(name, arguments or {})
        except Exception as e:  # 서버 오류도 LLM이 읽을 수 있게 결과로 돌려준다
            return ToolResult(f"도구 호출 실패: {e}", is_error=True, duration_s=time.monotonic() - started)
        text = "\n".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")
        return ToolResult(text, is_error=bool(res.isError), duration_s=round(time.monotonic() - started, 2))
