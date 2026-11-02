import json

from preflight.models import Snapshot
from rehearsal import cli
from rehearsal.compare import HIT, MISS, UNPREDICTED, compare, predict, selector_matches
from rehearsal.drain import BLOCKED_PDB, REPLACE_FAILED, REPLACED, UNMANAGED, DrainResult, PodOutcome
from rehearsal.report import to_json, to_markdown

from rehearsal_fakes import FakeCluster, pod


def deployment(name, replicas=1, node_selector=None, labels=None):
    return {"metadata": {"name": name, "namespace": "app"},
            "spec": {"replicas": replicas, "template": {"metadata": {"labels": labels or {}},
                                                        "spec": {"nodeSelector": node_selector or {}}}}}


SNAP = Snapshot({
    "deployments": [
        deployment("payment", labels={"app": "payment"}),
        deployment("legacy", node_selector={"eks.amazonaws.com/nodegroup": "ng-legacy"}, replicas=2),
        deployment("web", replicas=2),
    ],
    "poddisruptionbudgets": [{"metadata": {"name": "payment", "namespace": "app"},
                              "spec": {"minAvailable": 1, "selector": {"matchLabels": {"app": "payment"}}},
                              "status": {"expectedPods": 1, "disruptionsAllowed": 0}}],
    "pods": [{"metadata": {"name": "debug", "namespace": "app"}}],
})

PODS = [
    PodOutcome("app", "payment-1", "Deployment/app/payment", labels={"app": "payment"}, outcome=BLOCKED_PDB),
    PodOutcome("app", "legacy-1", "Deployment/app/legacy", outcome=REPLACE_FAILED),
    PodOutcome("app", "debug", "Pod/app/debug", outcome=UNMANAGED),
    PodOutcome("app", "web-1", "Deployment/app/web", outcome=REPLACED, evicted_at=0.1, replaced_after=4),
    PodOutcome("app", "web-2", "Deployment/app/web", outcome=REPLACED, downtime=True),
    PodOutcome("kube-system", "coredns-1", "Deployment/kube-system/coredns", outcome=REPLACED, downtime=True),
]


def rows_by_key(rows):
    return {(r.workload, r.problem): r for r in rows}


def test_prediction_vs_actual():
    rows = rows_by_key(compare(PODS, predict(SNAP), SNAP))
    assert rows[("Deployment/app/payment", "PDB에 막힘")].verdict == HIT
    assert rows[("Deployment/app/payment", "PDB에 막힘")].checks == ["pdb-blocks-drain"]
    # replica 1이라 다운타임을 예측했지만, PDB에 막혀 evict되지 않았다
    assert rows[("Deployment/app/payment", "다운타임 가능")].verdict == MISS
    assert rows[("Deployment/app/legacy", "재배치 실패")].verdict == HIT
    assert rows[("Pod/app/debug", "컨트롤러 없음")].verdict == HIT
    # replica 2인데 같은 노드에 몰려 있어 동시에 내려감 → 점검이 예측하지 못한 문제
    assert rows[("Deployment/app/web", "다운타임 가능")].verdict == UNPREDICTED


def test_system_namespaces_are_left_out_of_comparison_by_default():
    workloads = {r.workload for r in compare(PODS, predict(SNAP), SNAP)}
    assert "Deployment/kube-system/coredns" not in workloads
    workloads = {r.workload for r in compare(PODS, predict(SNAP, True), SNAP, include_system=True)}
    assert "Deployment/kube-system/coredns" in workloads


def test_selector_matches():
    assert selector_matches({"matchLabels": {"app": "a"}}, {"app": "a", "x": "y"})
    assert not selector_matches({"matchLabels": {"app": "a"}}, {"app": "b"})
    assert selector_matches({"matchExpressions": [{"key": "tier", "operator": "In", "values": ["web"]}]}, {"tier": "web"})
    assert not selector_matches({"matchExpressions": [{"key": "tier", "operator": "Exists"}]}, {})


def test_report_explains_eks_pod_eviction_failure_only_when_blocked():
    result = DrainResult(node="w1", context="kind-test", timeout=60, pods=PODS)
    md = to_markdown(result, compare(PODS, predict(SNAP), SNAP))
    assert "## PDB에 막힘" in md and "15분" in md and "PodEvictionFailure" in md
    assert "managed-node-update-behavior" in md
    ok = DrainResult(node="w1", context="kind-test", timeout=60, pods=[PODS[3]])
    assert "PodEvictionFailure" not in to_markdown(ok, [])
    data = json.loads(to_json(result, []))
    assert data["pods"][0]["outcome"] == BLOCKED_PDB


def test_cli_writes_reports_and_returns_1_when_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.collect, "from_cluster", lambda kubectl, context: SNAP)
    cluster = FakeCluster([pod("payment-1", labels={"app": "payment"})], evict={"payment-1": "pdb"})
    code = cli.main(["drain", "--node", "w1", "--timeout", "0", "--out", str(tmp_path)], runner=cluster)
    assert code == 1
    [run_dir] = tmp_path.iterdir()
    assert (run_dir / "drain-w1.md").exists() and (run_dir / "drain-w1.json").exists()
    assert (run_dir / "snapshot" / "deployments.json").exists()
    assert cluster.calls[-1][0] == "uncordon"
