"""Tests for the Agent loop (mocked LLM)."""

from unittest.mock import MagicMock, patch

from react.agent import Agent


def _chunk(content="", tool_calls=None, done=False):
    msg = {}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"model": "test", "message": msg, "done": done}


def _stream(*chunks):
    return list(chunks)


def test_agent_reads_file():
    client = MagicMock()
    client.chat.side_effect = [
        _stream(
            _chunk(tool_calls=[{"function": {"name": "read_file", "arguments": {"path": "main.py"}}}]),
            _chunk(done=True),
        ),
        _stream(_chunk(content="The file defines the CLI."), _chunk(done=True)),
    ]
    with patch("react.agent.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("read main.py", use_native=True)
        assert any(m.get("role") == "tool" for m in agent.messages)
        assert client.chat.call_count == 2


def test_agent_json_fallback():
    client = MagicMock()
    client.chat.side_effect = [
        _stream(_chunk(content='{"tool": "search_code", "args": {"query": "Agent"}}'), _chunk(done=True)),
        _stream(_chunk(content="DONE: Found it."), _chunk(done=True)),
    ]
    with patch("react.agent.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("search", use_native=False)
        assert len(agent.files_in_context) == 0


def test_self_heal_limit():
    client = MagicMock()
    fail_chunk = _stream(
        _chunk(tool_calls=[{"function": {"name": "run_command", "arguments": {"cmd": "false"}}}]),
        _chunk(done=True),
    )
    client.chat.side_effect = lambda *a, **k: fail_chunk
    with patch("react.agent.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("run false", use_native=True)
        system_msgs = [
            m for m in agent.messages
            if m.get("role") == "system" and "command failed" in m.get("content", "").lower()
        ]
        assert len(system_msgs) <= 2
