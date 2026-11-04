"""MCP 서버 구성과 안전장치. analyze와 eval이 같이 쓴다."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from rehearsal.guard import resolve_context

from .tools import ServerSpec

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KUBECONFIG = ROOT / "out" / "agent" / "kubeconfig-viewer"
RUNBOOKS_DIR = ROOT / "runbooks"


def kube_runner(kubeconfig: Path):
    def run(args: list[str], input: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run(["kubectl", "--kubeconfig", str(kubeconfig), *args], input=input,
                              capture_output=True, text=True)
    return run


def check_context(kubeconfig: Path, runner=None) -> str:
    """kubeconfig의 현재 컨텍스트가 kind-로 시작하는지 확인한다. 아니면 GuardError (MCP 서버를 띄우기 전에 멈춤)."""
    return resolve_context(runner or kube_runner(kubeconfig))


def _k8s_mcp_command() -> str:
    local = Path(sys.executable).parent / "kubernetes-mcp-server"
    found = str(local) if local.exists() else shutil.which("kubernetes-mcp-server")
    if not found:
        raise RuntimeError("kubernetes-mcp-server가 없습니다. pip install -e '.[agent]'로 설치하세요.")
    return found


def server_specs(kubeconfig: Path, with_preflight: bool = True) -> tuple[list[ServerSpec], Path]:
    """붙일 MCP 서버 두 개. kubernetes-mcp-server 설정 파일 경로도 돌려준다(호출한 쪽이 지운다)."""
    from mcp.client.stdio import get_default_environment

    cfg = Path(tempfile.mkstemp(prefix="k8s-mcp-", suffix=".toml")[1])
    cfg.write_text("\n".join([
        "# 에이전트가 만드는 임시 설정. 쓰기 도구를 모두 끈다.",
        "read_only = true",
        f'kubeconfig = "{kubeconfig.resolve()}"',
        'toolsets = ["core"]',
    ]) + "\n", encoding="utf-8")
    env = {**get_default_environment(), "KUBECONFIG": str(kubeconfig.resolve())}
    servers = [ServerSpec("kubernetes", _k8s_mcp_command(), ["--config", str(cfg)], env)]
    if with_preflight:
        env_py = {**env, "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")}
        servers.append(ServerSpec("preflight", sys.executable, ["-m", "preflight_mcp"], env_py))
    return servers, cfg
