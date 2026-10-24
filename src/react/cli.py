"""Typer CLI entry point for ReAct."""

from __future__ import annotations

import json

import ollama
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import Agent
from .tools import execute_tool
import react.utils as utils_mod

app = typer.Typer(add_completion=False, help="ReAct — a local-first AI coding agent.")
console = Console()

_HELP = """\
[bold]Slash commands[/bold]
  /help          Show this help
  /undo          Restore the most recent snapshot
  /clear         Clear conversation history
  /exit, /quit   Exit the REPL

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
    console.print(f"[yellow]Unknown command: {name}. Type /help.[/yellow]")
    return False


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
            agent.run(line, use_native=use_native)
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
