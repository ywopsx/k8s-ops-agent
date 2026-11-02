"""안전장치: kind 클러스터가 아니면 아무것도 하지 않고 멈춘다."""
from __future__ import annotations

from typing import Optional

from .kube import Runner

KIND_PREFIX = "kind-"


class GuardError(RuntimeError):
    pass


def resolve_context(run: Runner, requested: Optional[str] = None) -> str:
    """현재 컨텍스트와 --context가 모두 kind-로 시작하는지 확인하고, 이후 쓸 컨텍스트를 돌려준다.

    이 함수는 `kubectl config current-context` 외에는 아무 명령도 실행하지 않는다.
    """
    result = run(["config", "current-context"])
    current = result.stdout.strip() if result.returncode == 0 else ""
    if not current.startswith(KIND_PREFIX):
        raise GuardError(f"현재 컨텍스트({current or '없음'})가 {KIND_PREFIX}로 시작하지 않습니다. "
                         "rehearsal은 kind 클러스터에서만 실행합니다. 아무것도 바꾸지 않고 멈춥니다.")
    if requested is not None and not requested.startswith(KIND_PREFIX):
        raise GuardError(f"--context({requested})가 {KIND_PREFIX}로 시작하지 않습니다. "
                         "아무것도 바꾸지 않고 멈춥니다.")
    return requested or current
