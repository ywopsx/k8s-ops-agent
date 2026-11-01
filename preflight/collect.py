"""클러스터 또는 저장된 디렉터리에서 리소스를 읽어 Snapshot을 만든다. 읽기 전용."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import Snapshot

NAMESPACED = [
    "pods", "deployments", "statefulsets", "daemonsets", "jobs", "cronjobs",
    "poddisruptionbudgets", "ingresses", "horizontalpodautoscalers", "roles", "rolebindings",
]
CLUSTER_SCOPED = [
    "nodes", "flowschemas", "prioritylevelconfigurations", "clusterroles", "clusterrolebindings",
    "customresourcedefinitions",
]


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
            # 권한이 없거나 리소스 종류가 없는 클러스터도 있으니 건너뛰고 알린다.
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
