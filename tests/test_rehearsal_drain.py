import pytest

from rehearsal import cli
from rehearsal.drain import (
    BLOCKED_PDB, EVICT_ERROR, REPLACE_FAILED, REPLACED, SKIPPED, UNMANAGED, drain_node,
)
from rehearsal.guard import GuardError, resolve_context
from rehearsal.kube import GONE, PDB, PDB_MULTIPLE, Kube, classify_eviction_error

from rehearsal_fakes import PDB_429, PDB_500, FakeClock, FakeCluster, pod

WEB = ("ReplicaSet", "web-rs", "uid-web-rs")


def run_drain(cluster, **kw):
    kube = Kube(cluster, "kind-test")
    return drain_node(kube, "w1", clock=cluster.clock, sleep=cluster.clock.sleep, **kw)


def by_name(result):
    return {p.name: p for p in result.pods}


# --- guard -----------------------------------------------------------------
def test_non_kind_context_stops_before_any_other_command(capsys):
    cluster = FakeCluster([pod("web-1")], current="other-cluster")
    assert cli.main(["drain", "--node", "w1"], runner=cluster) == 2
    assert cluster.calls == [["config", "current-context"]]
    assert "멈춥니다" in capsys.readouterr().err


def test_non_kind_context_flag_is_rejected(capsys):
    cluster = FakeCluster([pod("web-1")], current="kind-test")
    assert cli.main(["drain", "--node", "w1", "--context", "other-cluster"], runner=cluster) == 2
    assert cluster.calls == [["config", "current-context"]]


def test_resolve_context_prefers_flag_when_both_kind():
    cluster = FakeCluster([], current="kind-a")
    assert resolve_context(cluster, "kind-b") == "kind-b"
    with pytest.raises(GuardError):
        resolve_context(FakeCluster([], current=""), None)


def test_every_command_carries_the_checked_context():
    cluster = FakeCluster([pod("web-1")], replace={"uid-web-rs": ("ready", 0)})
    run_drain(cluster)
    assert cluster.calls and all(c[-2:] == ["--context", "kind-test"] for c in cluster.calls)


# --- 분류 -------------------------------------------------------------------
def test_pods_are_classified_and_only_controlled_pods_are_evicted():
    pods = [
        pod("kube-proxy-x", ns="kube-system", owner=("DaemonSet", "kube-proxy", "uid-ds")),
        pod("etcd-w1", ns="kube-system", owner=("Node", "w1", "uid-node"),
            annotations={"kubernetes.io/config.mirror": "x"}),
        pod("job-done", owner=("Job", "j", "uid-job"), phase="Succeeded"),
        pod("debug-shell", owner=None),
        pod("web-1"),
    ]
    cluster = FakeCluster(pods, replace={"uid-web-rs": ("ready", 0)})
    result = by_name(run_drain(cluster))
    assert result["kube-proxy-x"].outcome == SKIPPED
    assert result["etcd-w1"].outcome == SKIPPED
    assert result["job-done"].outcome == SKIPPED
    assert result["debug-shell"].outcome == UNMANAGED
    assert result["web-1"].outcome == REPLACED
    evicted = [c[2] for c in cluster.calls if c[:2] == ["create", "--raw"]]
    assert evicted == ["/api/v1/namespaces/app/pods/web-1/eviction"]


def test_workload_ref_follows_replicaset_to_deployment():
    rs = {"metadata": {"name": "web-rs", "namespace": "app",
                       "ownerReferences": [{"kind": "Deployment", "name": "web", "uid": "uid-d", "controller": True}]}}
    cluster = FakeCluster([pod("web-1")], replicasets={("app", "web-rs"): rs}, replace={"uid-web-rs": ("ready", 0)})
    assert by_name(run_drain(cluster))["web-1"].workload == "Deployment/app/web"


# --- eviction ---------------------------------------------------------------
def test_eviction_error_classification():
    assert classify_eviction_error(PDB_429).status == PDB
    assert classify_eviction_error(PDB_500).status == PDB_MULTIPLE
    assert classify_eviction_error('Error from server (NotFound): pods "x" not found').status == GONE


def test_pdb_429_blocks_until_timeout():
    cluster = FakeCluster([pod("payment-1", owner=("ReplicaSet", "payment-rs", "uid-pay"))], evict={"payment-1": "pdb"})
    result = run_drain(cluster, timeout=10, interval=2)
    [p] = result.pods
    assert p.outcome == BLOCKED_PDB and "429" in p.note
    assert p.attempts == 6  # 0, 2, 4, 6, 8, 10초
    assert result.duration == 10 and not result.ok


def test_multiple_pdbs_500_is_also_pdb_block():
    # 한 Pod를 PDB 여러 개가 가리키면 eviction API가 500으로 거부한다. EKS 문서도 PodEvictionFailure 원인으로 든다.
    cluster = FakeCluster([pod("payment-1")], evict={"payment-1": "pdb-multiple"})
    [p] = run_drain(cluster, timeout=4).pods
    assert p.outcome == BLOCKED_PDB and "여러 개" in p.note and "500" in p.note


def test_not_found_counts_as_evicted():
    cluster = FakeCluster([pod("web-1")], evict={"web-1": "gone"}, replace={"uid-web-rs": ("ready", 0)})
    [p] = run_drain(cluster).pods
    assert p.outcome == REPLACED and p.evicted_at == 0


def test_other_eviction_errors_are_not_retried():
    cluster = FakeCluster([pod("web-1")], evict={"web-1": "error"})
    [p] = run_drain(cluster, timeout=10).pods
    assert p.outcome == EVICT_ERROR and p.attempts == 1 and "Forbidden" in p.note


# --- 대체 Pod -----------------------------------------------------------------
def test_replacement_time_and_downtime():
    # 같은 노드에 replica 2개가 모두 있으면, 두 번째 Pod를 evict할 때는 남은 Ready Pod가 없다.
    cluster = FakeCluster([pod("web-1"), pod("web-2")], replace={"uid-web-rs": ("ready", 5)})
    result = by_name(run_drain(cluster, timeout=30, interval=2))
    assert result["web-1"].outcome == REPLACED and result["web-2"].outcome == REPLACED
    assert result["web-1"].replaced_after == 6 and result["web-2"].replaced_after == 6  # 2초 간격으로 확인
    assert result["web-1"].downtime is False and result["web-2"].downtime is True


def test_replica_on_other_node_means_no_downtime():
    cluster = FakeCluster([pod("web-1"), pod("web-2", node="w2")], replace={"uid-web-rs": ("ready", 0)})
    assert by_name(run_drain(cluster))["web-1"].downtime is False


def test_pending_replacement_is_failure_with_scheduler_message():
    msg = "0/3 nodes are available: 1 node(s) didn't match Pod's node affinity/selector."
    cluster = FakeCluster([pod("legacy-1", owner=("ReplicaSet", "legacy-rs", "uid-legacy"))],
                          replace={"uid-legacy": ("pending", msg)})
    result = run_drain(cluster, timeout=6)
    [p] = result.pods
    assert p.outcome == REPLACE_FAILED and msg in p.note and p.downtime is True


def test_missing_replacement_is_failure():
    cluster = FakeCluster([pod("web-1")])  # 대체 Pod가 생기지 않음
    [p] = run_drain(cluster, timeout=4).pods
    assert p.outcome == REPLACE_FAILED and "Ready가 되지 않음" in p.note


# --- 정리 -------------------------------------------------------------------
def test_uncordon_runs_even_when_drain_fails():
    cluster = FakeCluster([pod("web-1")], evict={"web-1": "raise"})
    with pytest.raises(RuntimeError):
        run_drain(cluster)
    assert [c[0] for c in cluster.write_calls()] == ["cordon", "create", "uncordon"]


def test_keep_cordoned_skips_uncordon():
    cluster = FakeCluster([pod("web-1")], replace={"uid-web-rs": ("ready", 0)})
    result = run_drain(cluster, keep_cordoned=True)
    assert "uncordon" not in [c[0] for c in cluster.calls]
    assert result.uncordoned is False
