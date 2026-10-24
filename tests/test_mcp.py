"""Tests for MCP tool loading and routing (mocked)."""

from unittest.mock import patch

import react.mcp_client as mcp_mod
from react.tools import execute_tool


def test_load_mcp_tools_missing_config():
    with patch.object(mcp_mod, "_config_path", return_value=__import__("pathlib").Path("/nonexistent")):
        tools = mcp_mod.load_mcp_tools()
        assert tools == []


def test_tool_merge_and_route():
    # Simulate a loaded MCP tool
    fake_tool = {
        "type": "function",
        "function": {"name": "mcp_echo", "description": "echo (MCP:test)", "parameters": {}},
        "_mcp_server": "test",
    }
    mcp_mod._MCP_TOOLS = [fake_tool]
    mcp_mod._MCP_SERVERS = {"test": {"command": "echo", "args": []}}

    with patch("react.tools.call_mcp_tool", return_value="echoed") as mock_call:
        result = execute_tool("mcp_echo", {"text": "hi"})
        assert result == "echoed"
        mock_call.assert_called_once_with("mcp_echo", {"text": "hi"})

    # Cleanup
    mcp_mod._MCP_TOOLS = []
    mcp_mod._MCP_SERVERS = {}


def test_unknown_mcp_tool():
    mcp_mod._MCP_TOOLS = []
    mcp_mod._MCP_SERVERS = {}
    result = execute_tool("does_not_exist", {})
    assert result.startswith("[error]")
