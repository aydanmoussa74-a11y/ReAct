#!/usr/bin/env python3
"""ReAct CLI — Phase 1: agentic tool calling.

A local-first AI coding agent that streams a prompt to a local Ollama model
with read-only tools (read_file, search_code), executes tool calls, feeds
results back, and loops until done.  Falls back to a JSON system prompt
if the model doesn't support native tool-calling.
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
from rich.status import Status

from tools import TOOL_DEFINITIONS, execute_tool

app = typer.Typer(add_completion=False, help="ReAct — a local-first AI coding agent.")
console = Console()

MAX_ITERATIONS = 20

_FALLBACK_SYSTEM = (
    "You are a coding agent with tools. Output one of:\n"
    '  {"tool": "name", "args": {"arg": "value"}}  — then STOP\n'
    "  DONE: <final answer>\n"
    "Tools: read_file(path), search_code(query). One call per turn."
)


class Agent:
    """Conversation state and the ReAct tool-calling loop."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.client = ollama.Client()
        self.messages: list[dict] = []
        self.files_in_context = 0

    def run(self, prompt: str, use_native: bool) -> None:
        """Run the agent loop until the model produces a final answer."""
        self.messages.append({"role": "user", "content": prompt})
        if not use_native:
            self.messages.insert(0, {"role": "system", "content": _FALLBACK_SYSTEM})

        for iteration in range(1, MAX_ITERATIONS + 1):
            calls = self._chat(use_native)
            if not calls:
                break  # final answer was streamed
            for call in calls:
                self._execute_and_record(call)
        else:
            # for/else: runs when the loop completes without break
            console.print(Panel(
                f"[yellow]Reached the maximum of {MAX_ITERATIONS} iterations "
                f"without the model finishing.[/yellow]\n"
                "The response loop has been stopped to prevent runaway execution.",
                title="Max iterations",
            ))

    def _chat(self, use_native: bool) -> list[dict]:
        """Stream a chat response; return tool calls or [].

        Uses stream=True. Final answers are rendered token-by-token through a
        Rich Live panel as they arrive. Tool calls are accumulated and returned.
        """
        kwargs = {"model": self.model, "messages": self.messages, "stream": True}
        if use_native:
            kwargs["tools"] = TOOL_DEFINITIONS

        collected_content: list[str] = []
        accumulated_tool_calls: list[dict] = []
        live: Live | None = None
        live_parts: list[str] = []

        status = Status(
            f"[cyan]Thinking ({self.model})  "
            f"[dim]{self.files_in_context} files in context[/dim]",
            console=console, spinner="dots",
        )
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
                    # Stream final-answer tokens live as they arrive
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

        # Append the full assistant message to the conversation log.
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
            # Final answer was already streamed live token-by-token
            return []

        # --- JSON fallback path ---
        if not full_text.strip():
            return []

        done_match = re.match(r"^DONE:\s*(.*)", full_text.strip(), re.DOTALL)
        if done_match:
            # Already streamed the raw content; re-render the cleaned answer
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

    def _execute_and_record(self, call: dict) -> None:
        """Execute a tool call and append its result to the conversation."""
        if "function" in call:  # native format
            name = call["function"]["name"]
            args = call["function"].get("arguments", {})
        else:  # JSON fallback format
            name = call["tool"]
            args = call.get("args", {})

        result = execute_tool(name, args)
        if name == "read_file" and not result.startswith("[error]"):
            self.files_in_context += 1

        preview = result[:200] + ("…" if len(result) > 200 else "")
        console.print(Panel(preview, title=f"{name} result", border_style="green"))
        self.messages.append({"role": "tool", "content": result})

    def _stream_markdown(self, text: str) -> None:
        """Render markdown through a Rich Live panel, streaming word-by-word.
        Used as a fallback when the full answer is already collected."""
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
    return "llama3.2"  # let the next call fail with a clear message


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
    model: str = typer.Option(
        None, "--model", "-m", help="Ollama model to use (default: auto-detect)."),
) -> None:
    """Send PROMPT to a local Ollama model with read-only tools (Phase 1)."""
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
