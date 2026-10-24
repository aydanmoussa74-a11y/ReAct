"""Typer CLI entry point for ReAct."""

from __future__ import annotations

import json

import ollama
import typer
from rich.console import Console
from rich.panel import Panel

from .agent import Agent
from .tools import TOOL_DEFINITIONS
import react.utils as utils_mod

app = typer.Typer(add_completion=False, help="ReAct — a local-first AI coding agent.")
console = Console()


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


@app.command()
def main(
    prompt: str = typer.Argument(..., help="The prompt to send to the local LLM."),
    model: str = typer.Option(None, "--model", "-m", help="Ollama model to use."),
    dangerously_allow_dotfiles: bool = typer.Option(
        False, "--dangerously-allow-dotfiles",
        help="Allow writes to dotfiles. Use with caution."),
) -> None:
    """Send a prompt to a local Ollama model with tools."""
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
    console.print(Panel(f"[bold]{prompt}[/bold]", title=f"ReAct · {active_model}"))

    use_native = _model_supports_tools(active_model)
    console.print(f"[dim]Tool mode: {'native' if use_native else 'JSON fallback'}[/dim]")

    agent = Agent(active_model)
    try:
        agent.run(prompt, use_native=use_native)
    except Exception as exc:
        console.print(Panel(f"[red]Agent error:[/red]\n{exc}", title="Failed"))
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
