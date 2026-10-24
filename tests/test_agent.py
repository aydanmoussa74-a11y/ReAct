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
    with patch("react.agent.ollama.Client", return_value=client), patch("react.agent.Prompt.ask", return_value="y"):
        agent = Agent("llama3.2")
        agent.run("run false", use_native=True)
        system_msgs = [
            m for m in agent.messages
            if m.get("role") == "system" and "command failed" in m.get("content", "").lower()
        ]
        assert len(system_msgs) <= 2


def test_slash_exit_and_clear():
    """Slash commands should be handled without calling the LLM."""
    from react.cli import _handle_slash
    from react.agent import Agent
    agent = Agent("test")
    agent.messages.append({"role": "user", "content": "hi"})
    agent.files_in_context.add("a.py")
    assert _handle_slash("/clear", agent) is False
    assert agent.messages == []
    assert len(agent.files_in_context) == 0
    assert _handle_slash("/exit", agent) is True
    assert _handle_slash("/quit", agent) is True


def test_model_manager_local_list():
    """get_local_models should return a list (empty is fine if Ollama is down)."""
    from react.model_manager import get_local_models, RECOMMENDED_MODELS
    models = get_local_models()
    assert isinstance(models, list)
    assert len(RECOMMENDED_MODELS) >= 3



def test_native_mode_receives_investigation_system_prompt():
    client = MagicMock()
    client.chat.side_effect = [
        _stream(_chunk(content="I will inspect the project."), _chunk(done=True)),
    ]
    with patch("react.agent.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("inspect first", use_native=True)
    messages = client.chat.call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert "Codebase investigation protocol" in messages[0]["content"]
    assert "do not emit JSON tool calls as plain text" in messages[0]["content"]


def test_fallback_system_prompt_does_not_accumulate():
    client = MagicMock()
    client.chat.side_effect = [
        _stream(_chunk(content="DONE: first"), _chunk(done=True)),
        _stream(_chunk(content="DONE: second"), _chunk(done=True)),
    ]
    with patch("react.agent.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("first", use_native=False)
        agent.run("second", use_native=False)
    assert sum(1 for m in agent.messages if m.get("role") == "system") == 1
