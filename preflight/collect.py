"""클러스터 또는 저장된 디렉터리에서 리소스를 읽어 Snapshot을 만든다. 읽기 전용."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import Snapshot

NAMESPACED = [
    "pods", "deployments", "statefulsets", "daemonsets", "jobs", "cronjobs",
    "poddisruptionbudgets", "services", "ingresses", "horizontalpodautoscalers", "roles", "rolebindings",
    "targetgroupbindings",  # AWS Load Balancer Controller CRD. 설치되지 않은 클러스터에는 없다(OPTIONAL).
]
CLUSTER_SCOPED = [
    "nodes", "flowschemas", "prioritylevelconfigurations", "clusterroles", "clusterrolebindings",
    "customresourcedefinitions", "ingressclasses",
]

# 설치되지 않았을 수 있는 CRD. 이 kind만 "리소스 종류가 없음"일 때 경고 없이 건너뛴다.
# 기본 리소스(pods, nodes 등)가 없다고 나오면 점검을 못 한 것이므로 경고해야 한다.
OPTIONAL = {"targetgroupbindings"}

# kubectl이 "리소스 종류가 없음"을 알리는 문구
MISSING_KIND_MARKER = "the server doesn't have a resource type"


def _is_missing_kind(stderr: str) -> bool:
    return MISSING_KIND_MARKER in stderr


def from_cluster(kubectl: str = "kubectl", context: str | None = None) -> Snapshot:
    snap = Snapshot()
    for kind in NAMESPACED + CLUSTER_SCOPED:
        cmd = [kubectl, "get", kind, "-o", "json"]
        if kind in NAMESPACED:
            cmd.insert(3, "--all-namespaces")
        if context:
            cmd += ["--context", context]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if kind in OPTIONAL and _is_missing_kind(result.stderr):
                continue
            # 권한 오류 등 그 밖의 실패는 건너뛰되 알린다.
            print(f"[warn] {kind} 조회 실패: {result.stderr.strip().splitlines()[-1] if result.stderr else ''}")
            continue
        snap.resources[kind] = json.loads(result.stdout).get("items", [])
    return snap


def from_dir(path: str | Path) -> Snapshot:
    """<kind>.json 파일(kubectl get <kind> -o json 결과)을 모아 Snapshot으로 읽는다."""
    snap = Snapshot()
    for f in sorted(Path(path).glob("*.json")):
        snap.resources[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("items", [])
    return snap


def save(snap: Snapshot, path: str | Path) -> None:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    for kind, items in snap.resources.items():
        (out / f"{kind}.json").write_text(
            json.dumps({"apiVersion": "v1", "kind": "List", "items": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
