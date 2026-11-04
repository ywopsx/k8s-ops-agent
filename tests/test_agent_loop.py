import asyncio
import json

import pytest

from agent.alert import parse_webhook
from agent.loop import MAX_OUTPUT_CHARS, MODE_AGENT, MODE_FIXED, analyze, parse_action, to_causes
from agent.mask import mask
from agent.report import to_json, to_markdown

from agent_fakes import POD_ALERT, SVC_ALERT, FakeBackend, FakeToolBox, final, tool


def run(alert, replies, mode=MODE_AGENT, outputs=None, **kw):
    backend, box = FakeBackend(replies), FakeToolBox(outputs)
    result = asyncio.run(analyze(alert, box, backend, mode, runbooks="런북 내용", **kw))
    return result, backend, box


def test_mode_c_starts_with_pod_state_and_events_only():
    result, backend, box = run(POD_ALERT, [final("oom_killed")])
    assert [c[0] for c in box.calls] == ["pods_list_in_namespace", "pods_get", "events_list"]
    assert result.top_cause == "oom_killed" and result.agent_tool_calls == 0
    system, prompt = backend.prompts[0]
    assert '"action": "tool"' in system and "런북 내용" in system and "oom_killed" in system
    assert "남은 도구 호출: 5회" in prompt


def test_service_alert_without_pod_skips_pods_get():
    _, _, box = run(SVC_ALERT, [final("service_selector_mismatch")])
    assert [c[0] for c in box.calls] == ["pods_list_in_namespace", "events_list"]


def test_agent_tool_call_then_final():
    replies = [tool("pods_log", namespace="shop", name="report-worker-abc", previous=True, tail=500),
               final("app_config_error", "oom_killed")]
    result, backend, box = run(POD_ALERT, replies, outputs={"pods_log": "FATAL: ORDER_DB_URL is not set"})
    assert result.agent_tool_calls == 1
    # 로그는 log_lines(기본 50)를 넘지 않게 줄인다
    assert box.calls[-1] == ("pods_log", {"namespace": "shop", "name": "report-worker-abc", "previous": True, "tail": 50})
    assert "FATAL: ORDER_DB_URL is not set" in backend.prompts[1][1]
    assert [c.id for c in result.causes] == ["app_config_error", "oom_killed"]


def test_tool_calls_are_capped_and_final_is_forced():
    replies = [tool("events_list", namespace="shop")] * 7 + [final("oom_killed")]
    result, backend, box = run(POD_ALERT, replies, max_tool_calls=5)
    assert result.agent_tool_calls == 5
    assert "이제 결론(action=final)만 답한다" in backend.prompts[5][1]
    # 5회를 다 쓴 뒤의 도구 요청은 실행하지 않는다
    assert len([c for c in box.calls if c[0] == "events_list"]) == 1 + 5
    # 한도를 넘은 요청 2번은 거절되고, 그다음 결론을 받는다
    assert result.top_cause == "oom_killed" and not result.error


def test_endless_tool_requests_stop_with_error():
    result, _, _ = run(POD_ALERT, [tool("events_list", namespace="shop")] * 20, max_tool_calls=2)
    assert "결론(action=final)을 내지 않았습니다" in result.error
    assert len(result.llm_calls) == 5   # (2 + 1) + 2


def test_unknown_tool_is_refused_and_counted():
    replies = [tool("pods_delete", namespace="shop", name="x"), final("oom_killed")]
    result, backend, box = run(POD_ALERT, replies)
    assert "pods_delete" not in [c[0] for c in box.calls]
    assert result.agent_tool_calls == 1 and any("허용되지 않은 도구" in n for n in result.notes)
    assert "쓸 수 있는 도구가 아니다" in backend.prompts[1][1]


def test_mode_a_collects_fixed_set_and_calls_llm_once():
    result, backend, box = run(POD_ALERT, [final("oom_killed")], mode=MODE_FIXED)
    tools = [c[0] for c in box.calls]
    assert tools == ["pods_list_in_namespace", "pods_get", "events_list", "pods_log", "pods_log",
                     "resources_list", "resources_list", "resources_list"]
    assert box.calls[4][1]["previous"] is True
    assert len(backend.prompts) == 1 and '"action": "tool"' not in backend.prompts[0][0]
    assert result.agent_tool_calls == 0


def test_mode_a_refuses_tool_requests():
    result, backend, _ = run(POD_ALERT, [tool("events_list"), final("oom_killed")], mode=MODE_FIXED)
    assert result.top_cause == "oom_killed" and len(backend.prompts) == 2
    assert "더 조회할 수 없다" in backend.prompts[1][1]


def test_invalid_json_is_retried_once_then_fails():
    ok, _, _ = run(POD_ALERT, ["설명입니다", final("oom_killed")])
    assert ok.top_cause == "oom_killed" and not ok.error
    bad, _, _ = run(POD_ALERT, ["설명", "또 설명"])
    assert "JSON으로 읽지 못했습니다" in bad.error and bad.top_cause is None


def test_tool_output_is_masked_and_clipped_before_llm():
    secret = "password=hunter2 token: abc.def Authorization: Bearer abcdefghijkl from 10.1.2.3 " + "x" * (MAX_OUTPUT_CHARS + 10)
    result, backend, _ = run(POD_ALERT, [final("oom_killed")], outputs={"pods_get": secret})
    prompt = backend.prompts[0][1]
    for raw in ("hunter2", "abc.def", "abcdefghijkl", "10.1.2.3"):
        assert raw not in prompt
    assert "생략" in prompt
    obs = [o for o in result.observations if o.tool == "pods_get"][0]
    assert obs.chars == len(secret)


def test_parse_action_and_causes():
    assert parse_action('```json\n{"action": "final", "causes": []}\n```')["action"] == "final"
    assert parse_action('답: {"action": "tool", "tool": "x"} 끝')["tool"] == "x"
    with pytest.raises(ValueError):
        parse_action('{"action": "run"}')
    causes, notes = to_causes([{"id": "made_up", "confidence": 0.5}, {"id": "oom_killed", "confidence": 2}])
    assert [c.id for c in causes] == ["oom_killed", "other"] and causes[0].confidence == 1.0 and notes


def test_report_contains_required_sections(tmp_path):
    rb = tmp_path / "oom-killed.md"
    rb.write_text("# 런북\n조치")
    result, _, _ = run(POD_ALERT, [tool("pods_log", namespace="shop", name="p"), final("oom_killed")])
    md = to_markdown(result, rb)
    for section in ("## 원인 후보", "## 조회한 리소스 상태", "## 런북", "## 확인 명령", "## 조회 기록", "## 실행 정보"):
        assert section in md
    assert "fake-model" in md and "LLM 선택 1회" in md
    data = json.loads(to_json(result, rb))
    assert data["top_cause"] == "oom_killed" and data["llm"]["input_tokens"] == 200 and data["runbook"] == "runbooks/oom-killed.md"


def test_parse_webhook_picks_firing_alert():
    payload = {"commonLabels": {"namespace": "shop"},
               "alerts": [{"status": "resolved", "labels": {"alertname": "Old"}},
                          {"status": "firing", "labels": {"alertname": "KubePodCrashLooping", "pod": "p"},
                           "annotations": {"summary": "요약"}}]}
    a = parse_webhook(payload)
    assert (a.name, a.namespace, a.pod, a.summary) == ("KubePodCrashLooping", "shop", "p", "요약")
    with pytest.raises(ValueError):
        parse_webhook({"alerts": []})


def test_mask_patterns():
    text = ("DB_PASSWORD=s3cr3t api_key: 'k-123' url=postgres://app:pw@db:5432/x "
            "AKIAABCDEFGHIJKLMNOP eyJhbGciOiJ.eyJzdWIiOiIx.c2lnbmF0dXJl ip 192.168.0.10")
    out = mask(text)
    for raw in ("s3cr3t", "k-123", "app:pw", "AKIAABCDEFGHIJKLMNOP", "eyJhbGciOiJ", "192.168.0.10"):
        assert raw not in out
    assert "DB_PASSWORD=***" in out and "x.x.x.x" in out
