"""Lightweight MCP client for ReAct (stdio transport)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

# Module-level registry populated by load_mcp_tools
_MCP_TOOLS: list[dict] = []
_MCP_SERVERS: dict[str, dict] = {}  # name -> server config


def _config_path(path: str | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    return Path.home() / ".react" / "mcp_config.json"


def load_mcp_tools(config_path: str | None = None) -> list[dict]:
    """Read MCP config and return tool definitions compatible with TOOL_DEFINITIONS.

    On any failure (missing config, connection error, missing SDK) returns an empty
    list so ReAct continues to work with local tools only.
    """
    global _MCP_TOOLS, _MCP_SERVERS
    _MCP_TOOLS = []
    _MCP_SERVERS = {}

    cfg_file = _config_path(config_path)
    if not cfg_file.exists():
        return []

    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    servers = cfg.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []

    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        command = spec.get("command")
        args = spec.get("args", [])
        if not command:
            continue
        _MCP_SERVERS[name] = {"command": command, "args": args}
        tools = _fetch_tools_sync(name, command, args)
        _MCP_TOOLS.extend(tools)

    return list(_MCP_TOOLS)


def _fetch_tools_sync(server_name: str, command: str, args: list[str]) -> list[dict]:
    """Run the async list_tools in a fresh event loop. Returns [] on any error."""
    try:
        return asyncio.run(_list_tools(server_name, command, args))
    except Exception:
        return []


async def _list_tools(server_name: str, command: str, args: list[str]) -> list[dict]:
    """Connect via stdio and return ReAct-compatible tool definitions."""
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        from mcp.client.stdio import StdioServerParameters
    except ImportError:
        return []

    params = StdioServerParameters(command=command, args=args)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = []
                for t in getattr(result, "tools", []) or []:
                    schema = getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": (t.description or "") + f" (MCP:{server_name})",
                            "parameters": schema,
                        },
                        "_mcp_server": server_name,
                    })
                return tools
    except Exception:
        return []


def get_mcp_tools() -> list[dict]:
    """Return the currently loaded MCP tool definitions."""
    return list(_MCP_TOOLS)


def get_mcp_servers() -> dict[str, dict]:
    """Return the currently configured servers."""
    return dict(_MCP_SERVERS)


def call_mcp_tool(name: str, arguments: dict) -> str:
    """Call an MCP tool by name. Returns a string result or an error message."""
    # Find which server owns this tool
    server_name = None
    for tool in _MCP_TOOLS:
        if tool["function"]["name"] == name:
            server_name = tool.get("_mcp_server")
            break
    if not server_name or server_name not in _MCP_SERVERS:
        return f"[error] MCP tool '{name}' is not available."

    spec = _MCP_SERVERS[server_name]
    try:
        return asyncio.run(_call_tool(server_name, spec["command"], spec["args"], name, arguments))
    except Exception as exc:
        return f"[error] MCP call failed: {exc}"


async def _call_tool(server_name: str, command: str, args: list[str], tool_name: str, arguments: dict) -> str:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
    except ImportError:
        return "[error] mcp package is not installed."

    params = StdioServerParameters(command=command, args=args)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # result.content is usually a list of content blocks
                parts = []
                for block in getattr(result, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
                    else:
                        parts.append(str(block))
                return "\n".join(parts) if parts else str(result)
    except Exception as exc:
        return f"[error] MCP server '{server_name}' call failed: {exc}"
