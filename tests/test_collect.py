import subprocess

from preflight import collect


def fake_kubectl(failures):
    """kind별로 실패를 흉내 내는 subprocess.run 대체 함수. failures: {kind: stderr}"""
    def run(cmd, capture_output, text):
        kind = cmd[2]
        if kind in failures:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=failures[kind])
        return subprocess.CompletedProcess(cmd, 0, stdout='{"items": []}', stderr="")
    return run


def test_missing_kind_is_skipped_silently(monkeypatch, capsys):
    # CRD(예: LBC의 TargetGroupBinding)가 설치되지 않은 클러스터
    monkeypatch.setattr(collect.subprocess, "run", fake_kubectl({
        "targetgroupbindings": 'error: the server doesn\'t have a resource type "targetgroupbindings"\n'}))
    snap = collect.from_cluster()
    assert "targetgroupbindings" not in snap.resources
    assert "services" in snap.resources
    assert capsys.readouterr().out == ""


def test_missing_core_kind_still_warns(monkeypatch, capsys):
    # 기본 리소스가 "없음"으로 나오면 점검을 못 한 것이므로, 문제없음처럼 보이지 않게 경고한다.
    monkeypatch.setattr(collect.subprocess, "run", fake_kubectl({
        "deployments": 'error: the server doesn\'t have a resource type "deployments"\n'}))
    snap = collect.from_cluster()
    assert "deployments" not in snap.resources
    assert "[warn] deployments 조회 실패" in capsys.readouterr().out


def test_other_failures_still_warn(monkeypatch, capsys):
    monkeypatch.setattr(collect.subprocess, "run", fake_kubectl({
        "roles": 'Error from server (Forbidden): roles.rbac.authorization.k8s.io is forbidden: '
                 'User "viewer" cannot list resource "roles" in API group "rbac.authorization.k8s.io" at the cluster scope\n'}))
    snap = collect.from_cluster()
    assert "roles" not in snap.resources
    out = capsys.readouterr().out
    assert "[warn] roles 조회 실패" in out and "Forbidden" in out
