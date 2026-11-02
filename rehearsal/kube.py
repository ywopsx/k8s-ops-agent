"""rehearsal에서 쓰는 kubectl 호출. 읽기와 쓰기를 나눠 두고, 테스트에서는 실행기를 가짜로 바꾼다.

모든 호출에 guard가 확인한 --context를 붙인다. 실행 중에 다른 터미널에서 현재 컨텍스트를 바꿔도
다른 클러스터로 넘어가지 않게 하기 위해서다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

# run(args, input=None) -> CompletedProcess. args에는 kubectl 실행 파일 이름이 들어가지 않는다.
Runner = Callable[..., subprocess.CompletedProcess]


def kubectl_runner(kubectl: str = "kubectl") -> Runner:
    def run(args: list[str], input: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run([kubectl, *args], input=input, capture_output=True, text=True)
    return run


class KubectlError(RuntimeError):
    pass


# eviction 결과
EVICTED = "evicted"            # 201: evict 요청이 받아들여짐
GONE = "gone"                  # 404: 이미 사라진 Pod. 빠져나간 것으로 본다
PDB = "pdb"                    # 429: PDB가 중단을 허용하지 않음
PDB_MULTIPLE = "pdb-multiple"  # 500: 한 Pod에 PDB가 여러 개라 eviction API가 처리하지 못함
ERROR = "error"                # 그 밖의 실패 (권한 등)


@dataclass(frozen=True)
class EvictResult:
    status: str
    message: str = ""


def classify_eviction_error(stderr: str) -> EvictResult:
    """kubectl create --raw .../eviction 실패 출력을 분류한다."""
    lines = stderr.strip().splitlines()
    message = lines[-1] if lines else ""
    if "more than one PodDisruptionBudget" in stderr:
        return EvictResult(PDB_MULTIPLE, message)
    if "(TooManyRequests)" in stderr or "disruption budget" in stderr:
        return EvictResult(PDB, message)
    if "(NotFound)" in stderr:
        return EvictResult(GONE, message)
    return EvictResult(ERROR, message)


class Kube:
    def __init__(self, run: Runner, context: str):
        self._run_raw = run
        self.context = context

    def _run(self, args: list[str], input: Optional[str] = None) -> subprocess.CompletedProcess:
        return self._run_raw([*args, "--context", self.context], input=input)

    def _json(self, args: list[str]) -> dict:
        result = self._run([*args, "-o", "json"])
        if result.returncode != 0:
            raise KubectlError(f"kubectl {' '.join(args)} 실패: {result.stderr.strip()}")
        return json.loads(result.stdout)

    # --- 읽기 ---------------------------------------------------------------
    def node_exists(self, node: str) -> bool:
        return self._run(["get", "node", node, "-o", "name"]).returncode == 0

    def pods_on_node(self, node: str) -> list[dict]:
        return self._json(["get", "pods", "--all-namespaces", "--field-selector", f"spec.nodeName={node}"])["items"]

    def pods_in_namespace(self, namespace: str) -> list[dict]:
        return self._json(["get", "pods", "-n", namespace])["items"]

    def get(self, kind: str, name: str, namespace: str) -> Optional[dict]:
        result = self._run(["get", kind, name, "-n", namespace, "-o", "json"])
        return json.loads(result.stdout) if result.returncode == 0 else None

    # --- 쓰기 (rehearsal 전용) ------------------------------------------------
    def cordon(self, node: str) -> None:
        self._check(self._run(["cordon", node]), "cordon")

    def uncordon(self, node: str) -> None:
        self._check(self._run(["uncordon", node]), "uncordon")

    def evict(self, namespace: str, name: str) -> EvictResult:
        body = json.dumps({"apiVersion": "policy/v1", "kind": "Eviction",
                           "metadata": {"name": name, "namespace": namespace}})
        result = self._run(["create", "--raw", f"/api/v1/namespaces/{namespace}/pods/{name}/eviction", "-f", "-"],
                           input=body)
        if result.returncode == 0:
            return EvictResult(EVICTED)
        return classify_eviction_error(result.stderr)

    @staticmethod
    def _check(result: subprocess.CompletedProcess, what: str) -> None:
        if result.returncode != 0:
            raise KubectlError(f"{what} 실패: {result.stderr.strip()}")
