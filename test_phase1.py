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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk(content: str = "", tool_calls=None, done: bool = False) -> dict:
    """Build a streaming chat chunk dict (mimics ollama stream format)."""
    msg: dict = {}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"model": "test", "message": msg, "done": done}


def _stream(*chunks) -> list[dict]:
    """Return a list of chunk dicts (simulates a streaming iterator)."""
    return list(chunks)


# ---------------------------------------------------------------------------
# Part 1: Direct tool tests
# ---------------------------------------------------------------------------

def test_read_file():
    """read_file should return the contents of an existing file."""
    content = read_file("tools.py")
    assert "def read_file" in content, "Should read tools.py contents"
    assert not content.startswith("[error]"), "Should not error on valid file"
    print("  ✅ read_file('tools.py') — reads file correctly")


def test_read_file_not_found():
    """read_file should report an error for non-existent files."""
    result = read_file("does_not_exist.py")
    assert result.startswith("[error]"), f"Expected error, got: {result}"
    print("  ✅ read_file('nonexistent') — errors gracefully")


def test_read_file_traversal():
    """read_file should block path traversal attempts."""
    result = read_file("../../../etc/hostname")
    assert result.startswith("[error]"), f"Traversal should be blocked, got: {result}"
    print("  ✅ read_file('../../etc/hostname') — traversal blocked")


def test_read_file_truncation():
    """read_file should truncate files larger than 50KB with a warning."""
    import tempfile, os
    from pathlib import Path
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=".") as f:
        # Write 60KB of content (over the 50KB limit).
        f.write("# big file\n" + "x" * (55 * 1024))
        fname = f.name
    try:
        content = read_file(fname)
        assert "[truncated:" in content, f"Expected truncation warning, got: {content[:80]}"
        assert len(content) < 55 * 1024 + 500, "Should be truncated"
    finally:
        os.unlink(fname)
    print("  ✅ read_file(>50KB) — truncates with warning")


def test_search_code():
    """search_code should find matches across source files."""
    result = search_code("read_file")
    assert "read_file" in result, f"Should find 'read_file', got: {result}"
    assert "tools.py" in result, "Should find matches in tools.py"
    print("  ✅ search_code('read_file') — finds matches in tools.py")


def test_search_code_extensions():
    """search_code should search across multiple file extensions."""
    assert ".md" in SEARCH_EXTENSIONS
    assert ".js" in SEARCH_EXTENSIONS
    assert ".yaml" in SEARCH_EXTENSIONS
    result = search_code("ReAct")
    assert len(result) > 0, "Should find 'ReAct' in README.md"
    assert "README.md" in result, f"Should find README.md, got: {result[:100]}"
    print("  ✅ search_code — searches .py, .md, .js, etc.")


def test_search_code_no_match():
    """search_code should report no matches for a genuinely absent string."""
    needle = "zzq" + "xz9" + "_absent_" + "zzz"
    result = search_code(needle)
    assert "No matches" in result, f"Expected no matches, got: {result[:80]}"
    print("  ✅ search_code('nonexistent') — reports no matches")


def test_execute_tool():
    """execute_tool should dispatch correctly to tool functions."""
    result = execute_tool("read_file", {"path": "requirements.txt"})
    assert "typer" in result, f"Should contain 'typer', got: {result}"
    print("  ✅ execute_tool('read_file') — dispatches correctly")


def test_execute_tool_unknown():
    """execute_tool should handle unknown tools gracefully."""
    result = execute_tool("rm", {})
    assert "Unknown tool" in result
    print("  ✅ execute_tool('unknown') — reports unknown tool")


def test_execute_tool_broad_exception():
    """execute_tool should catch all exceptions, not just TypeError."""
    # Pass an argument that will cause a non-TypeError exception.
    result = execute_tool("read_file", {"path": None})
    assert result.startswith("[error]"), f"Should catch exception, got: {result}"
    print("  ✅ execute_tool — broad exception handling works")


def test_tool_definitions():
    """TOOL_DEFINITIONS should list both tools with proper schema."""
    names = [td["function"]["name"] for td in TOOL_DEFINITIONS]
    assert "read_file" in names and "search_code" in names
    for td in TOOL_DEFINITIONS:
        assert "parameters" in td["function"]
        assert "required" in td["function"]["parameters"]
    print("  ✅ TOOL_DEFINITIONS — both tools defined with schema")


# ---------------------------------------------------------------------------
# Part 2: Agent loop tests (with mock LLM returning streaming chunks)
# ---------------------------------------------------------------------------

def _make_mock_client_native():
    """Mock client: native tools path with streaming chunks."""
    client = MagicMock()
    # Turn 1: tool call (read main.py)
    client.chat.side_effect = [
        _stream(
            _chunk(tool_calls=[{"function": {"name": "read_file",
                  "arguments": {"path": "main.py"}}}]),
            _chunk(done=True),
        ),
        # Turn 2: final answer
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
    """Mock client: JSON fallback path with streaming chunks."""
    client = MagicMock()
    client.chat.side_effect = [
        # Turn 1: JSON tool call (streamed as a single content chunk)
        _stream(
            _chunk(content='{"tool": "search_code", "args": {"query": "read_file"}}'),
            _chunk(done=True),
        ),
        # Turn 2: final answer
        _stream(
            _chunk(content="DONE: Found read_file in tools.py."),
            _chunk(done=True),
        ),
    ]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "text"}}
    return client


def test_agent_native_tools():
    """Agent should call read_file via native tools, then produce a final answer."""
    from main import Agent

    with patch("main.ollama.Client", return_value=_make_mock_client_native()):
        agent = Agent("llama3.2")
        agent.run("read main.py", use_native=True)
        assert agent.files_in_context == 1, f"Expected 1 file, got {agent.files_in_context}"
        assert len(agent.messages) >= 3, "Should have user + assistant(tool) + tool + assistant(done)"
        print("  ✅ Agent (native tools) — calls read_file, tracks files, finishes")


def test_agent_json_fallback():
    """Agent should parse JSON tool calls in fallback mode."""
    from main import Agent

    with patch("main.ollama.Client", return_value=_make_mock_client_json()):
        agent = Agent("llama3.2")
        agent.run("search for read_file usage", use_native=False)
        assert agent.files_in_context == 0, "search_code shouldn't increment file counter"
        print("  ✅ Agent (JSON fallback) — parses JSON, calls search_code, finishes")


def test_agent_multi_turn():
    """Agent should loop through multiple tool calls."""
    from main import Agent

    client = MagicMock()
    client.chat.side_effect = [
        # Turn 1: read main.py
        _stream(
            _chunk(tool_calls=[{"function": {"name": "read_file",
                  "arguments": {"path": "main.py"}}}]),
            _chunk(done=True),
        ),
        # Turn 2: search for Agent class
        _stream(
            _chunk(tool_calls=[{"function": {"name": "search_code",
                  "arguments": {"query": "class Agent"}}}]),
            _chunk(done=True),
        ),
        # Turn 3: final answer
        _stream(
            _chunk(content="DONE: main.py has an Agent class with a run loop."),
            _chunk(done=True),
        ),
    ]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "tools"}}

    with patch("main.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("understand the Agent class", use_native=True)
        assert agent.files_in_context == 1  # only read_file increments
        assert client.chat.call_count == 3
        print("  ✅ Agent (multi-turn) — read_file → search_code → done (3 turns)")


def test_agent_max_iterations():
    """Agent should stop after MAX_ITERATIONS even if the model keeps tool-calling."""
    from main import Agent, MAX_ITERATIONS

    client = MagicMock()
    # Model keeps returning a tool call forever.
    call_chunk = _stream(
        _chunk(tool_calls=[{"function": {"name": "read_file",
              "arguments": {"path": "main.py"}}}]),
        _chunk(done=True),
    )
    client.chat.side_effect = [call_chunk for _ in range(MAX_ITERATIONS + 5)]
    client.list.return_value = {"models": []}
    client.show.return_value = {"details": {"format": "tools"}}

    with patch("main.ollama.Client", return_value=client):
        agent = Agent("llama3.2")
        agent.run("keep going forever", use_native=True)
        assert client.chat.call_count == MAX_ITERATIONS, (
            f"Should stop at {MAX_ITERATIONS}, got {client.chat.call_count}")
        print(f"  ✅ Agent (max iterations) — stops after {MAX_ITERATIONS} turns")


# ---------------------------------------------------------------------------

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
