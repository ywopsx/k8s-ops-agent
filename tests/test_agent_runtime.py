import json
import subprocess
from pathlib import Path

import pytest

from agent import cli
from agent.eval import Scenario, aggregate, score, summary_markdown
from agent.loop import Analysis, Cause
from agent.tools import ALLOWED_TOOLS
from preflight_mcp.tool import run_preflight
from rehearsal.guard import GuardError

from agent_fakes import POD_ALERT

FIXTURES = Path(__file__).parent / "fixtures"


def fake_kubectl(context):
    calls = []

    def run(args, input=None):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, context + "\n", "")
    return run, calls


def test_cli_stops_before_starting_mcp_when_not_kind(monkeypatch, capsys):
    run, calls = fake_kubectl("prod-cluster")
    monkeypatch.setattr(cli, "check_context", lambda kc: __import__("agent.runtime", fromlist=["x"]).check_context(kc, run))
    started = []
    monkeypatch.setattr(cli, "server_specs", lambda *a, **k: started.append(1))
    code = cli.main(["analyze", "--alert", "x.json"])
    assert code == 2 and not started
    assert calls == [["config", "current-context"]]
    assert "kind-" in capsys.readouterr().err


def test_allowlist_has_only_read_tools():
    names = set().union(*ALLOWED_TOOLS.values())
    for word in ("delete", "exec", "run", "create", "update", "scale", "patch"):
        assert not any(word in n.split("_") for n in names if n != "run_preflight")
    assert "run_preflight" in names


def test_run_preflight_from_fixture_snapshot_filters_severity():
    data = json.loads(run_preflight(snapshot_dir=str(FIXTURES / "snapshot")))
    sev = {f["severity"] for f in data["findings"]}
    assert sev <= {"HIGH", "MEDIUM"} and "HIGH" in sev
    assert data["omitted_below_threshold"] >= 1     # vpc-cni-env INFO 등
    high = json.loads(run_preflight(snapshot_dir=str(FIXTURES / "snapshot"), min_severity="high"))
    assert {f["severity"] for f in high["findings"]} == {"HIGH"}


def test_run_preflight_refuses_non_kind_context_and_captures_warnings():
    run, calls = fake_kubectl("prod-cluster")
    data = json.loads(run_preflight(runner=run, collector=lambda **k: pytest.fail("수집하면 안 됨")))
    assert "kind-" in data["error"] and calls == [["config", "current-context"]]

    def noisy_collector(context):
        print("[warn] nodes 조회 실패: forbidden")   # stdout에 찍혀도 MCP 통로를 더럽히지 않아야 한다
        from preflight.models import Snapshot
        return Snapshot()
    run, _ = fake_kubectl("kind-ops-agent-viewer")
    data = json.loads(run_preflight(runner=run, collector=noisy_collector))
    assert data["context"] == "kind-ops-agent-viewer" and data["warnings"] == ["[warn] nodes 조회 실패: forbidden"]
    assert json.loads(run_preflight(min_severity="LOW"))["error"]


def test_eval_scoring_and_summary():
    s = Scenario("A", "OOMKilled", "a.json", "oom_killed")
    right = Analysis(alert=POD_ALERT, mode="c", backend="fake", causes=[Cause("oom_killed", 0.9)], duration_s=10)
    wrong = Analysis(alert=POD_ALERT, mode="c", backend="fake", causes=[Cause("app_config_error", 0.6)], duration_s=20)
    failed = Analysis(alert=POD_ALERT, mode="c", backend="fake", causes=[Cause("oom_killed", 0.9)], error="실패")
    runs = [score(s, "c", i, "m", a) for i, a in enumerate((right, wrong, failed), 1)]
    assert [r.correct for r in runs] == [True, False, False]   # 오류가 난 실행은 틀린 것으로 센다
    [row] = aggregate(runs)
    assert row["correct"] == 1 and row["runs"] == 3 and row["avg_seconds"] == 10.0
    md = summary_markdown(runs, [s])
    assert "| m | C | 1/3 |" in md and "A OOMKilled" in md
