import json

import pytest

from preflight.checks import (
    Context, check_al2_nodes, check_nodegroup_pinned, check_pdb_blocks_drain, check_removed_apis,
    check_single_replica, check_unmanaged_pods, check_vpc_cni_env, run_all,
)
from preflight.models import Severity, Snapshot, version_tuple

CTX = Context(target_version="1.33")


def deployment(name="web", ns="app", replicas=2, node_selector=None, affinity=None):
    spec = {"nodeSelector": node_selector or {}}
    if affinity:
        spec["affinity"] = affinity
    return {"metadata": {"name": name, "namespace": ns},
            "spec": {"replicas": replicas, "template": {"spec": spec}}}


# --- nodegroup-pinned ------------------------------------------------------
def test_nodegroup_pinned_by_node_selector():
    snap = Snapshot({"deployments": [deployment(node_selector={"eks.amazonaws.com/nodegroup": "ng-legacy"})]})
    [f] = check_nodegroup_pinned(snap, CTX)
    assert f.severity == Severity.HIGH and f.ref == "Deployment/app/web"


def test_nodegroup_pinned_by_affinity_and_cronjob():
    aff = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
        {"matchExpressions": [{"key": "eks.amazonaws.com/nodegroup", "operator": "In", "values": ["ng-a"]}]}]}}}
    cron = {"metadata": {"name": "batch", "namespace": "app"},
            "spec": {"jobTemplate": {"spec": {"template": {"spec": {"affinity": aff}}}}}}
    snap = Snapshot({"cronjobs": [cron]})
    assert [f.ref for f in check_nodegroup_pinned(snap, CTX)] == ["CronJob/app/batch"]


def test_role_label_is_not_flagged():
    snap = Snapshot({"deployments": [deployment(node_selector={"node-role": "app"})]})
    assert check_nodegroup_pinned(snap, CTX) == []


def test_platform_pods_in_kube_system_are_still_checked():
    # 실무에서 문제였던 건 kube-system의 플랫폼 Pod(LB Controller 등)였다.
    snap = Snapshot({"deployments": [deployment(ns="kube-system",
                                                node_selector={"eks.amazonaws.com/nodegroup": "mgmt"})]})
    assert len(check_nodegroup_pinned(snap, CTX)) == 1


# --- pdb-blocks-drain ------------------------------------------------------
def test_pdb_with_zero_disruptions_allowed():
    pdb = {"metadata": {"name": "web", "namespace": "app"}, "spec": {"minAvailable": 1},
           "status": {"expectedPods": 1, "disruptionsAllowed": 0}}
    [f] = check_pdb_blocks_drain(Snapshot({"poddisruptionbudgets": [pdb]}), CTX)
    assert f.check == "pdb-blocks-drain"


def test_pdb_with_room_is_ok():
    pdb = {"metadata": {"name": "web", "namespace": "app"}, "spec": {"minAvailable": 1},
           "status": {"expectedPods": 3, "disruptionsAllowed": 2}}
    assert check_pdb_blocks_drain(Snapshot({"poddisruptionbudgets": [pdb]}), CTX) == []


# --- unmanaged-pod / single-replica ---------------------------------------
def test_unmanaged_pod_and_mirror_pod():
    bare = {"metadata": {"name": "debug", "namespace": "app"}}
    mirror = {"metadata": {"name": "etcd", "namespace": "app",
                           "annotations": {"kubernetes.io/config.mirror": "x"}}}
    owned = {"metadata": {"name": "web-1", "namespace": "app", "ownerReferences": [{"kind": "ReplicaSet"}]}}
    found = check_unmanaged_pods(Snapshot({"pods": [bare, mirror, owned]}), CTX)
    assert [f.name for f in found] == ["debug"]


def test_single_replica_skips_system_namespaces_by_default():
    snap = Snapshot({"deployments": [deployment(replicas=1), deployment(name="dns", ns="kube-system", replicas=1)]})
    assert [f.name for f in check_single_replica(snap, CTX)] == ["web"]
    ctx = Context(target_version="1.33", include_system=True)
    assert len(check_single_replica(snap, ctx)) == 2


# --- removed-api -----------------------------------------------------------
def with_last_applied(obj, api_version, kind):
    obj.setdefault("metadata", {}).setdefault("annotations", {})[
        "kubectl.kubernetes.io/last-applied-configuration"] = json.dumps({"apiVersion": api_version, "kind": kind})
    return obj


@pytest.mark.parametrize("target,expected", [("1.31", 0), ("1.32", 1), ("1.35", 1)])
def test_flowschema_v1beta3_removed_in_132(target, expected):
    fs = with_last_applied({"metadata": {"name": "custom"}}, "flowcontrol.apiserver.k8s.io/v1beta3", "FlowSchema")
    found = check_removed_apis(Snapshot({"flowschemas": [fs]}), Context(target_version=target))
    assert len(found) == expected


def test_current_api_is_not_flagged():
    ing = with_last_applied({"metadata": {"name": "web", "namespace": "app"}}, "networking.k8s.io/v1", "Ingress")
    assert check_removed_apis(Snapshot({"ingresses": [ing]}), CTX) == []


# --- al2-node --------------------------------------------------------------
def node(name, os_image):
    return {"metadata": {"name": name}, "status": {"nodeInfo": {"osImage": os_image}}}


def test_al2_nodes_are_high_from_133():
    snap = Snapshot({"nodes": [node("a", "Amazon Linux 2"), node("b", "Amazon Linux 2023.6.20250115")]})
    [f] = check_al2_nodes(snap, Context(target_version="1.33"))
    assert f.name == "a" and f.severity == Severity.HIGH
    [f] = check_al2_nodes(snap, Context(target_version="1.32"))
    assert f.severity == Severity.MEDIUM


# --- vpc-cni-env -----------------------------------------------------------
def aws_node(env):
    return {"metadata": {"name": "aws-node", "namespace": "kube-system"},
            "spec": {"template": {"spec": {"containers": [
                {"name": "aws-node", "env": [{"name": k, "value": v} for k, v in env.items()]}]}}}}


def test_cni_overwritten_settings_are_detected():
    # add-on 업데이트로 Custom Networking 설정이 기본값으로 덮어써진 상황을 재현
    snap = Snapshot({"daemonsets": [aws_node({"AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "false",
                                               "ENABLE_PREFIX_DELEGATION": "true"})]})
    ctx = Context(target_version="1.33", cni_expected_env={"AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "true",
                                                            "ENABLE_PREFIX_DELEGATION": "true"})
    found = check_vpc_cni_env(snap, ctx)
    high = [f for f in found if f.severity == Severity.HIGH]
    assert len(high) == 1 and "AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG" in high[0].message
    assert any(f.severity == Severity.INFO for f in found)


def test_no_aws_node_means_no_cni_findings():
    assert check_vpc_cni_env(Snapshot({"daemonsets": []}), CTX) == []


# --- 공통 -------------------------------------------------------------------
def test_run_all_sorts_high_first():
    snap = Snapshot({"deployments": [deployment(replicas=1, node_selector={"eks.amazonaws.com/nodegroup": "x"})]})
    found = run_all(snap, CTX)
    assert [f.severity for f in found] == sorted([f.severity for f in found], reverse=True)


def test_version_parsing():
    assert version_tuple("v1.33.2") == (1, 33)
    with pytest.raises(ValueError):
        version_tuple("latest")
