import json
import subprocess

import pytest

from agent.llm import BLOCK_ARGS, ClaudeCLIBackend, LLMError, ToolsNotDisabledError, parse_stream_json


def stream(tools=(), servers=(), result="{}", is_error=False, usage=None, cost=0.01):
    events = [{"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": list(servers), "model": "m"},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": result}]}},
              {"type": "result", "subtype": "success", "is_error": is_error, "result": result, "duration_ms": 1200,
               "usage": usage if usage is not None else {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 7,
                                  "cache_creation_input_tokens": 3},
               "total_cost_usd": cost, "modelUsage": {"claude-test-model": {}}}]
    return "\n".join(json.dumps(e) for e in events)


def test_command_disables_builtin_tools_and_external_config():
    cmd = ClaudeCLIBackend(model="claude-test-model").command("시스템")
    assert cmd[:2] == ["claude", "-p"]
    # 내장 도구 전부 끄기, MCP 서버 없음, 사용자·프로젝트 설정 읽지 않음
    i = cmd.index("--tools")
    assert cmd[i + 1] == ""
    assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
    j = cmd.index("--setting-sources")
    assert cmd[j + 1] == ""
    assert cmd[cmd.index("--system-prompt") + 1] == "시스템"
    assert cmd[cmd.index("--model") + 1] == "claude-test-model"
    assert all(a in cmd for a in BLOCK_ARGS)
    # 위험한 권한 우회 옵션은 넣지 않는다
    assert not any("dangerously" in a or "bypass" in a.lower() for a in cmd)


def test_complete_runs_in_empty_dir_with_prompt_on_stdin():
    seen = {}

    def run(cmd, input, capture_output, text, timeout, cwd):
        seen.update(cmd=cmd, input=input, cwd=cwd)
        return subprocess.CompletedProcess(cmd, 0, stream(result='{"action":"final"}'), "")

    res = ClaudeCLIBackend(run=run).complete("sys", "질문")
    assert seen["input"] == "질문" and "ops-agent-llm-" in seen["cwd"]
    assert res.text == '{"action":"final"}'
    assert (res.input_tokens, res.output_tokens, res.cache_read_tokens, res.cache_creation_tokens) == (10, 5, 7, 3)
    assert res.cost_usd == 0.01 and res.model == "claude-test-model"


@pytest.mark.parametrize("tools, servers", [(["Bash"], []), ([], [{"name": "x", "status": "connected"}])])
def test_session_with_tools_is_rejected(tools, servers):
    # 내장 도구나 MCP 서버가 살아 있으면 답을 쓰지 않고 멈춘다
    with pytest.raises(ToolsNotDisabledError):
        parse_stream_json(stream(tools=tools, servers=servers))


def test_missing_init_or_error_result():
    with pytest.raises(LLMError):
        parse_stream_json('{"type":"result","result":"x"}', 1, "auth error")
    with pytest.raises(LLMError):
        parse_stream_json(stream(is_error=True, result="rate limit"))


def test_usage_may_be_missing():
    res = parse_stream_json(stream(usage={}, cost=None))
    assert res.input_tokens is None and res.cost_usd is None
