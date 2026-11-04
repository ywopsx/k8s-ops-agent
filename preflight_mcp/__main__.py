"""`python -m preflight_mcp` — stdio MCP 서버. 의존성: pip install -e '.[agent]' (mcp)"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tool import run_preflight as _run_preflight

mcp = FastMCP("preflight")


@mcp.tool()
def run_preflight(target_version: str = "1.33", include_system: bool = False, min_severity: str = "MEDIUM") -> str:
    """EKS 업그레이드·노드 교체 사전 점검(읽기 전용). 노드그룹 이름에 묶인 스케줄링, drain을 막는 PDB,
    제거되는 API, 단독 Pod, replica 1개, 한 노드에 몰린 replica 등을 찾아 JSON으로 돌려준다.
    kind 컨텍스트에서만 실행한다. min_severity 미만(INFO 등)은 개수만 알려 준다."""
    return _run_preflight(target_version=target_version, include_system=include_system, min_severity=min_severity)


if __name__ == "__main__":
    mcp.run()
