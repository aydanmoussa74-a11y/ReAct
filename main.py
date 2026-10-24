#!/usr/bin/env python3
"""ReAct CLI — Phase 1 + Phase 2: agentic tool calling with write confirmation.

Local-first AI coding agent. Phase 1: read-only tools + streaming.
Phase 2: write_file / edit_file with human confirmation, snapshots, undo.
"""

from __future__ import annotations

import json
import re

import ollama
import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from rich.syntax import Syntax

from tools import ALLOW_DOTFILES, TOOL_DEFINITIONS, execute_tool
import tools as tools_mod

app = typer.Typer(add_completion=False, help="ReAct — a local-first AI coding agent.")
console = Console()

MAX_ITERATIONS = 20

_FALLBACK_SYSTEM = (
    "You are a coding agent with tools. Output one of:\n"
    '  {"tool": "name", "args": {"arg": "value"}}  — then STOP\n'
    "  DONE: <final answer>\n"
    "Tools: read_file(path), search_code(query), write_file(path, content), "
    "edit_file(path, diff), undo(). One call per turn."
)


class Agent:
    """Conversation state and the ReAct tool-calling loop."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.client = ollama.Client()
        self.messages: list[dict] = []
        self.files_in_context: set[str] = set()
        self.files_modified: set[str] = set()

    def _status_text(self) -> str:
        ctx = len(self.files_in_context)
        mod = len(self.files_modified)
        return (f"[cyan]Thinking ({self.model})  "
                f"[dim]{ctx} files in context · {mod} modified[/dim]")

    def run(self, prompt: str, use_native: bool) -> None:
        """Run the agent loop until the model produces a final answer."""
        self.messages.append({"role": "user", "content": prompt})
        if not use_native:
            self.messages.insert(0, {"role": "system", "content": _FALLBACK_SYSTEM})

        for iteration in range(1, MAX_ITERATIONS + 1):
            calls = self._chat(use_native)
            if not calls:
                break
            for call in calls:
                self._execute_and_record(call)
        else:
            console.print(Panel(
                f"[yellow]Reached the maximum of {MAX_ITERATIONS} iterations "
                f"without the model finishing.[/yellow]\n"
                "The response loop has been stopped to prevent runaway execution.",
                title="Max iterations",
            ))

    def _chat(self, use_native: bool) -> list[dict]:
        """Stream a chat response; return tool calls or []."""
        kwargs = {"model": self.model, "messages": self.messages, "stream": True}
        if use_native:
            kwargs["tools"] = TOOL_DEFINITIONS

        collected_content: list[str] = []
        accumulated_tool_calls: list[dict] = []
        live: Live | None = None
        live_parts: list[str] = []

        status = Status(self._status_text(), console=console, spinner="dots")
        status.start()

        try:
            stream = self.client.chat(**kwargs)
            chunks = [stream] if isinstance(stream, dict) else stream
            for chunk in chunks:
                msg = chunk.get("message", {})
                content = msg.get("content", "") or ""
                tcs = msg.get("tool_calls") or []

                if tcs:
                    accumulated_tool_calls = tcs
                    if live is not None:
                        live.stop()
                        live = None

                if content:
                    collected_content.append(content)
                    if not accumulated_tool_calls:
                        if live is None:
                            status.stop()
                            live = Live(console=console, refresh_per_second=20)
                            live.start()
                        live_parts.append(content)
                        live.update(Markdown("".join(live_parts)))

                if chunk.get("done", False):
                    break
        finally:
            status.stop()
            if live is not None:
                live.stop()

        full_msg = {"role": "assistant"}
        full_text = "".join(collected_content)
        if full_text:
            full_msg["content"] = full_text
        if accumulated_tool_calls and use_native:
            full_msg["tool_calls"] = accumulated_tool_calls
        self.messages.append(full_msg)

        if use_native:
            if accumulated_tool_calls:
                for tc in accumulated_tool_calls:
                    fn = tc["function"]
                    console.print(f"  [yellow]→ {fn['name']}({json.dumps(fn.get('arguments', {}))})[/yellow]")
                return accumulated_tool_calls
            return []

        # JSON fallback
        if not full_text.strip():
            return []

        done_match = re.match(r"^DONE:\s*(.*)", full_text.strip(), re.DOTALL)
        if done_match:
            self._stream_markdown(done_match.group(1).strip())
            return []

        calls: list[dict] = []
        for line in full_text.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("DONE"):
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "tool" in obj and "args" in obj:
                    calls.append(obj)
                    console.print(f"  [yellow]→ {obj['tool']}({json.dumps(obj['args'])})[/yellow]")
            except json.JSONDecodeError:
                continue
        return calls

    def _confirm_write(self, name: str, args: dict) -> bool:
        """Show a diff preview and ask for confirmation. Returns True if approved."""
        path = args.get("path", "")
        if name == "write_file":
            content = args.get("content", "")
            preview = Syntax(content[:2000], "text", theme="monokai", line_numbers=True)
            console.print(Panel(preview, title=f"write_file → {path}", border_style="yellow"))
        elif name == "edit_file":
            diff = args.get("diff", "")
            # Colorize simple +/- lines
            colored = []
            for line in diff.splitlines()[:80]:
                if line.startswith("+") and not line.startswith("+++"):
                    colored.append(f"[green]{line}[/green]")
                elif line.startswith("-") and not line.startswith("---"):
                    colored.append(f"[red]{line}[/red]")
                else:
                    colored.append(line)
            console.print(Panel("\n".join(colored), title=f"edit_file → {path}", border_style="yellow"))
        else:
            return True

        choice = Prompt.ask(
            "[bold]Apply this change?[/bold]",
            choices=["y", "n", "e", "a"],
            default="n",
            show_choices=True,
        )
        if choice == "y":
            return True
        if choice == "n":
            console.print("[dim]Skipped.[/dim]")
            return False
        if choice == "a":
            console.print("[red]Aborted.[/red]")
            raise typer.Exit(code=0)
        # "e" — let user edit the args manually (simple path for now)
        if name == "write_file":
            new_content = Prompt.ask("New content", default=args.get("content", ""))
            args["content"] = new_content
        elif name == "edit_file":
            new_diff = Prompt.ask("New diff", default=args.get("diff", ""))
            args["diff"] = new_diff
        return True

    def _execute_and_record(self, call: dict) -> None:
        """Execute a tool call (with confirmation for writes) and record result."""
        if "function" in call:
            name = call["function"]["name"]
            args = call["function"].get("arguments", {})
        else:
            name = call["tool"]
            args = call.get("args", {})

        if name in ("write_file", "edit_file"):
            if not self._confirm_write(name, args):
                result = "[skipped] User declined the change."
                self.messages.append({"role": "tool", "content": result})
                return

        result = execute_tool(name, args)

        if name == "read_file" and not result.startswith("[error]"):
            self.files_in_context.add(args.get("path", ""))
        if name in ("write_file", "edit_file") and result.startswith("[ok]"):
            self.files_modified.add(args.get("path", ""))

        preview = result[:300] + ("…" if len(result) > 300 else "")
        console.print(Panel(preview, title=f"{name} result", border_style="green"))
        self.messages.append({"role": "tool", "content": result})

    def _stream_markdown(self, text: str) -> None:
        """Render markdown through a Rich Live panel (fallback path)."""
        words = text.split(" ")
        collected: list[str] = []
        with Live(refresh_per_second=15, console=console) as live:
            for i, word in enumerate(words):
                collected.append(word)
                if i < len(words) - 1:
                    collected.append(" ")
                live.update(Markdown("".join(collected)))


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
    """Check if *model* advertises tool-calling support."""
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
        help="Allow writes to dotfiles (.env, .git/*, etc.). Use with caution."),
) -> None:
    """Send PROMPT to a local Ollama model with tools (Phase 1 + 2)."""
    if dangerously_allow_dotfiles:
        tools_mod.ALLOW_DOTFILES = True
        console.print("[yellow]Warning: dotfile writes are enabled.[/yellow]")

    err = _check_ollama()
    if err:
        console.print(Panel(
            f"[red]Could not connect to Ollama:[/red]\n{err}\n\n"
            "Start it with `ollama serve`.", title="Connection error"))
        raise typer.Exit(code=1)

    active_model = _resolve_model(model)
    console.print(Panel(f"[bold]{prompt}[/bold]", title=f"ReAct · {active_model}"))

    use_native = _model_supports_tools(active_model)
    console.print(f"[dim]Tool mode: {'native' if use_native else 'JSON fallback'}[/dim]")

    agent = Agent(active_model)
    try:
        agent.run(prompt, use_native=use_native)
    except Exception as exc:
        console.print(Panel(f"[red]Agent error:[/red]\n{exc}", title="Failed"))
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
