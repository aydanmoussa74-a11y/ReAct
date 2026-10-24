#!/usr/bin/env python3
"""Phase 1 test script — demonstrates the ReAct agent reading a file
and searching for a pattern.

Since Ollama isn't available in this environment, this script:
  1. Tests the tools directly (path safety, read, search, execute).
  2. Tests the Agent loop with a mock LLM client that simulates
     streaming responses (both native and JSON fallback modes).

Run:  python test_phase1.py
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from tools import execute_tool, read_file, search_code, TOOL_DEFINITIONS
from tools import SEARCH_EXTENSIONS, MAX_READ_BYTES


def _chunk(content: str = "", tool_calls=None, done: bool = False) -> dict:
    msg: dict = {}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"model": "test", "message": msg, "done": done}


def _stream(*chunks) -> list[dict]:
    return list(chunks)


def test_read_file():
    content = read_file("tools.py")
    assert "def read_file" in content
    assert not content.startswith("[error]")
    print("  ✅ read_file('tools.py') — reads file correctly")


def test_read_file_not_found():
    result = read_file("does_not_exist.py")
    assert result.startswith("[error]")
    print("  ✅ read_file('nonexistent') — errors gracefully")


def test_read_file_traversal():
    result = read_file("../../../etc/hostname")
    assert result.startswith("[error]")
    print("  ✅ read_file('../../etc/hostname') — traversal blocked")


def test_read_file_truncation():
    import tempfile, os
    from pathlib import Path
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=".") as f:
        f.write("# big file\n" + "x" * (55 * 1024))
        fname = f.name
    try:
        content = read_file(fname)
        assert "[truncated:" in content
    finally:
        os.unlink(fname)
    print("  ✅ read_file(>50KB) — truncates with warning")


def test_search_code():
    result = search_code("read_file")
    assert "read_file" in result
    assert "tools.py" in result
    print("  ✅ search_code('read_file') — finds matches in tools.py")


def test_search_code_extensions():
    assert ".md" in SEARCH_EXTENSIONS
    result = search_code("ReAct")
    assert "README.md" in result
    print("  ✅ search_code — searches .py, .md, .js, etc.")


def test_search_code_no_match():
    needle = "zzq" + "xz9" + "_absent_" + "zzz"
    result = search_code(needle)
    assert "No matches" in result
    print("  ✅ search_code('nonexistent') — reports no matches")


def test_execute_tool():
    result = execute_tool("read_file", {"path": "requirements.txt"})
    assert "typer" in result
    print("  ✅ execute_tool('read_file') — dispatches correctly")


def test_execute_tool_unknown():
    result = execute_tool("rm", {})
    assert "Unknown tool" in result
    print("  ✅ execute_tool('unknown') — reports unknown tool")


def test_execute_tool_broad_exception():
    result = execute_tool("read_file", {"path": None})
    assert result.startswith("[error]")
    print("  ✅ execute_tool — broad exception handling works")


def test_tool_definitions():
    names = [td["function"]["name"] for td in TOOL_DEFINITIONS]
    assert "read_file" in names and "search_code" in names
    for td in TOOL_DEFINITIONS:
        assert "parameters" in td["function"]
        assert "required" in td["function"]["parameters"]
    print("  ✅ TOOL_DEFINITIONS — tools defined with schema")


def _make_mock_client_native():
    client = MagicMock()
    client.chat.side_effect = [
        _stream(
            _chunk(tool_calls=[{"function": {"name": "read_file", "arguments": {"path": "main.py"}}}]),
            _chunk(done=True),
        ),
        _stream(
            _chunk(content="The file main.py defines a Typer CLI."),
            _chunk(content=" It has an Agent class. DONE."),
            _chunk(done=True),
        ),
    ]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "tools"}}
    return client


def _make_mock_client_json():
    client = MagicMock()
    client.chat.side_effect = [
        _stream(
            _chunk(content='{"tool": "search_code", "args": {"query": "read_file"}}'),
            _chunk(done=True),
        ),
        _stream(
            _chunk(content="DONE: Found read_file in tools.py."),
            _chunk(done=True),
        ),
    ]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "text"}}
    return client


def test_agent_native_tools():
    from main import Agent
    with patch("main.ollama.Client", return_value=_make_mock_client_native()):
        agent = Agent("llama3.2")
        agent.run("read main.py", use_native=True)
        assert "main.py" in agent.files_in_context
        assert len(agent.messages) >= 3
        print("  ✅ Agent (native tools) — calls read_file, tracks files, finishes")


def test_agent_json_fallback():
    from main import Agent
    with patch("main.ollama.Client", return_value=_make_mock_client_json()):
        agent = Agent("llama3.2")
        agent.run("search for read_file usage", use_native=False)
        assert len(agent.files_in_context) == 0
        print("  ✅ Agent (JSON fallback) — parses JSON, calls search_code, finishes")


def test_agent_multi_turn():
    from main import Agent
    client = MagicMock()
    client.chat.side_effect = [
        _stream(_chunk(tool_calls=[{"function": {"name": "read_file", "arguments": {"path": "main.py"}}}]), _chunk(done=True)),
        _stream(_chunk(tool_calls=[{"function": {"name": "search_code", "arguments": {"query": "class Agent"}}}]), _chunk(done=True)),
        _stream(_chunk(content="DONE: main.py has an Agent class with a run loop."), _chunk(done=True)),
    ]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "tools"}}
    with patch("main.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("understand the Agent class", use_native=True)
        assert "main.py" in agent.files_in_context
        assert client.chat.call_count == 3
        print("  ✅ Agent (multi-turn) — read_file → search_code → done (3 turns)")


def test_agent_max_iterations():
    from main import Agent, MAX_ITERATIONS
    client = MagicMock()
    call_chunk = _stream(_chunk(tool_calls=[{"function": {"name": "read_file", "arguments": {"path": "main.py"}}}]), _chunk(done=True))
    client.chat.side_effect = [call_chunk for _ in range(MAX_ITERATIONS + 5)]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "tools"}}
    with patch("main.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("keep going forever", use_native=True)
        assert client.chat.call_count == MAX_ITERATIONS
        print(f"  ✅ Agent (max iterations) — stops after {MAX_ITERATIONS} turns")


def main():
    print("=" * 60)
    print("ReAct Phase 1 — Test Suite")
    print("=" * 60)
    print("\n[Part 1: tools.py direct tests]")
    test_read_file()
    test_read_file_not_found()
    test_read_file_traversal()
    test_read_file_truncation()
    test_search_code()
    test_search_code_extensions()
    test_search_code_no_match()
    test_execute_tool()
    test_execute_tool_unknown()
    test_execute_tool_broad_exception()
    test_tool_definitions()
    print("\n[Part 2: Agent loop tests (mocked LLM, streaming)]")
    test_agent_native_tools()
    test_agent_json_fallback()
    test_agent_multi_turn()
    test_agent_max_iterations()
    print("\n" + "=" * 60)
    print("All tests passed! ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
