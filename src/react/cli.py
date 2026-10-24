"""Typer CLI entry point for ReAct."""

from __future__ import annotations

import json
import subprocess

from .ollama_compat import ollama
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .agent import Agent
from .tools import execute_tool
from .model_manager import RECOMMENDED_MODELS, get_local_models, pull_model
from .git_utils import is_git_repo, get_staged_diff, execute_commit
from .mcp_client import load_mcp_tools, get_mcp_tools, get_mcp_servers
import react.utils as utils_mod

app = typer.Typer(add_completion=False, help="ReAct — a local-first AI coding agent.")
console = Console()

_HELP = """\
[bold]Slash commands[/bold]
  /help              Show this help
  /model             List recommended models and local status
  /model <name>      Switch to (and optionally download) a model
  /commit            Generate and apply a Conventional Commit from staged changes
  /mcp status        Show connected MCP servers and tools
  /mcp reload        Reload MCP config and reconnect
  /undo              Restore the most recent snapshot
  /clear             Clear conversation history
  /exit, /quit       Exit the REPL

Type a normal prompt to talk to the agent.
Ctrl+C cancels the current generation and returns to the prompt.
"""


def _check_ollama() -> str | None:
    try:
        ollama.Client().list()
        return None
    except Exception as exc:
        return str(exc)


def _resolve_model(requested: str | None) -> str:
    if requested:
        return requested
    client = ollama.Client()
    try:
        models = client.list().get("models", [])
        for candidate in ("llama3.2", "qwen2.5-coder:7b"):
            if any(m["model"] == candidate for m in models):
                return candidate
    except Exception:
        pass
    return "llama3.2"


def _model_supports_tools(model: str) -> bool:
    try:
        info = json.dumps(ollama.Client().show(model)).lower()
        return "tools" in info or "tool" in info
    except Exception:
        return False


def _handle_slash(cmd: str, agent: Agent) -> bool:
    """Handle a slash command. Return True if the REPL should exit."""
    parts = cmd.strip().split()
    name = parts[0].lower()
    if name in ("/exit", "/quit"):
        console.print("[dim]Goodbye.[/dim]")
        return True
    if name == "/help":
        console.print(Panel(_HELP, title="Help", border_style="cyan"))
        return False
    if name == "/clear":
        agent.messages.clear()
        agent.files_in_context.clear()
        agent.files_modified.clear()
        agent._cmd_retries.clear()
        console.print("[green]Conversation history cleared.[/green]")
        return False
    if name == "/undo":
        result = execute_tool("undo", {})
        console.print(Panel(result, title="undo", border_style="green"))
        return False
    if name == "/model":
        _handle_model(parts[1:] if len(parts) > 1 else [], agent)
        return False
    if name == "/commit":
        _handle_commit(agent)
        return False
    if name == "/mcp":
        _handle_mcp(parts[1:] if len(parts) > 1 else ["status"])
        return False
    console.print(f"[yellow]Unknown command: {name}. Type /help.[/yellow]")
    return False


def _handle_mcp(args: list[str]) -> None:
    """Show MCP status or reload config."""
    sub = args[0].lower() if args else "status"
    if sub == "reload":
        tools = load_mcp_tools()
        console.print(f"[green]Reloaded MCP config. {len(tools)} tools available.[/green]")
        return
    servers = get_mcp_servers()
    tools = get_mcp_tools()
    if not servers:
        console.print("[dim]No MCP servers configured. Create ~/.react/mcp_config.json[/dim]")
        return
    table = Table(title="MCP Servers", show_header=True, header_style="bold cyan")
    table.add_column("Server")
    table.add_column("Tools")
    by_server: dict[str, list[str]] = {}
    for t in tools:
        srv = t.get("_mcp_server", "?")
        by_server.setdefault(srv, []).append(t["function"]["name"])
    for name in servers:
        tool_list = ", ".join(by_server.get(name, [])) or "(none)"
        table.add_row(name, tool_list)
    console.print(table)


def _propose_commit_message(agent: Agent, diff: str) -> str:
    """Ask the model for a single Conventional Commit message."""
    system = (
        "Analyze this git diff and generate a single, concise Conventional Commit message "
        "(e.g., feat:, fix:, refactor:, docs:). Do not include any other text, just the commit message."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"```diff\n{diff}\n```"},
    ]
    try:
        resp = agent.client.chat(model=agent.model, messages=messages, stream=False)
        msg = resp.get("message", {}).get("content", "").strip()
        for line in msg.splitlines():
            line = line.strip().strip('"').strip("'")
            if line:
                return line
        return "chore: update"
    except Exception:
        return "chore: update"


def _handle_commit(agent: Agent) -> None:
    """Interactive Conventional Commit flow from staged changes."""
    if not is_git_repo():
        console.print("[red]Not a git repository. Initialize one with `git init` first.[/red]")
        return

    diff = get_staged_diff()
    if diff is None:
        answer = Prompt.ask(
            "[yellow]No staged changes. Would you like me to run `git add .`?[/yellow]",
            choices=["y", "n"],
            default="n",
        )
        if answer.lower() != "y":
            console.print("[dim]Aborted.[/dim]")
            return
        try:
            subprocess.run(["git", "add", "."], check=False, capture_output=True, text=True)
        except Exception as exc:
            console.print(f"[red]git add failed: {exc}[/red]")
            return
        diff = get_staged_diff()
        if diff is None:
            console.print("[yellow]Still no staged changes. Nothing to commit.[/yellow]")
            return

    proposed = _propose_commit_message(agent, diff)
    console.print(Panel(proposed, title="Proposed commit message", border_style="cyan"))

    choice = Prompt.ask(
        "[yellow]Apply this commit?[/yellow]",
        choices=["y", "n", "e"],
        default="n",
    )
    if choice == "n":
        console.print("[dim]Aborted.[/dim]")
        return
    if choice == "e":
        proposed = Prompt.ask("Commit message", default=proposed).strip()
        if not proposed:
            console.print("[dim]Empty message. Aborted.[/dim]")
            return

    ok, output = execute_commit(proposed)
    if ok:
        console.print(Panel(output or f"Committed: {proposed}", title="Commit successful", border_style="green"))
    else:
        console.print(Panel(output or "Unknown error", title="Commit failed", border_style="red"))


def _handle_model(args: list[str], agent: Agent) -> None:
    """List recommended models or switch the active model."""
    local = set(get_local_models())
    if not args:
        table = Table(title="Recommended Models", show_header=True, header_style="bold cyan")
        table.add_column("Model")
        table.add_column("Local", justify="center")
        for name in RECOMMENDED_MODELS:
            status = "✅" if name in local else "❌"
            table.add_row(name, status)
        console.print(table)
        if agent.model:
            console.print(f"[dim]Active model: {agent.model}[/dim]")
        return

    target = args[0]
    if target in local:
        agent.model = target
        console.print(f"[green]Switched to {target}.[/green]")
        return

    answer = Prompt.ask(
        f"[yellow]Model {target} not found locally. Download it now?[/yellow]",
        choices=["y", "n"],
        default="n",
    )
    if answer.lower() != "y":
        console.print("[dim]Cancelled.[/dim]")
        return
    if pull_model(target):
        agent.model = target
        console.print(f"[green]Downloaded and switched to {target}.[/green]")
    else:
        console.print(f"[red]Could not download {target}.[/red]")


def _repl(agent: Agent, use_native: bool) -> None:
    """Interactive REPL loop. Agent state persists across turns."""
    console.print("[dim]Interactive mode. Type /help for commands.[/dim]")
    while True:
        try:
            line = Prompt.ask("[cyan]react>[/cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break
        if not line:
            continue
        if line.startswith("/"):
            if _handle_slash(line, agent):
                break
            continue
        try:
            # Re-detect capabilities after /model switches the active model.
            agent.run(line, use_native=_model_supports_tools(agent.model))
        except KeyboardInterrupt:
            console.print("\n[yellow]Generation cancelled.[/yellow]")
            continue
        except Exception as exc:
            console.print(Panel(f"[red]Agent error:[/red]\n{exc}", title="Failed"))


@app.command()
def main(
    prompt: str = typer.Argument(None, help="Optional prompt. Omit to enter interactive REPL."),
    model: str = typer.Option(None, "--model", "-m", help="Ollama model to use."),
    dangerously_allow_dotfiles: bool = typer.Option(
        False, "--dangerously-allow-dotfiles",
        help="Allow writes to dotfiles. Use with caution."),
) -> None:
    """Send a prompt to a local Ollama model, or start an interactive session."""
    if dangerously_allow_dotfiles:
        utils_mod.ALLOW_DOTFILES = True
        console.print("[yellow]Warning: dotfile writes are enabled.[/yellow]")

    err = _check_ollama()
    if err:
        console.print(Panel(
            f"[red]Could not connect to Ollama:[/red]\n{err}\n\nStart it with `ollama serve`.",
            title="Connection error",
        ))
        raise typer.Exit(1)

    active_model = _resolve_model(model)
    use_native = _model_supports_tools(active_model)
    console.print(f"[dim]Tool mode: {'native' if use_native else 'JSON fallback'}[/dim]")

    agent = Agent(active_model)

    if prompt is None:
        _repl(agent, use_native)
        return

    console.print(Panel(f"[bold]{prompt}[/bold]", title=f"ReAct · {active_model}"))
    try:
        agent.run(prompt, use_native=use_native)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(130)
    except Exception as exc:
        console.print(Panel(f"[red]Agent error:[/red]\n{exc}", title="Failed"))
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
