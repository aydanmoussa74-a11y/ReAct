"""ReAct agent loop with streaming, confirmation, and self-healing."""

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

from .tools import TOOL_DEFINITIONS, execute_tool

console = Console()
MAX_ITERATIONS = 20

_FALLBACK_SYSTEM = (
    "You are a coding agent with tools. Output one of:\n"
    '  {"tool": "name", "args": {"arg": "value"}}  — then STOP\n'
    "  DONE: <final answer>\n"
    "Tools: read_file, search_code, write_file, edit_file, undo, run_command. "
    "One call per turn."
)


class Agent:
    def __init__(self, model: str) -> None:
        self.model = model
        self.client = ollama.Client()
        self.messages: list[dict] = []
        self.files_in_context: set[str] = set()
        self.files_modified: set[str] = set()
        self._cmd_retries: dict[str, int] = {}

    def _status_text(self) -> str:
        return (f"[cyan]Thinking ({self.model})  "
                f"[dim]{len(self.files_in_context)} files in context · "
                f"{len(self.files_modified)} modified[/dim]")

    def run(self, prompt: str, use_native: bool) -> None:
        self.messages.append({"role": "user", "content": prompt})
        if not use_native:
            self.messages.insert(0, {"role": "system", "content": _FALLBACK_SYSTEM})

        for _ in range(1, MAX_ITERATIONS + 1):
            calls = self._chat(use_native)
            if not calls:
                break
            for call in calls:
                self._execute_and_record(call)
        else:
            console.print(Panel(
                f"[yellow]Reached the maximum of {MAX_ITERATIONS} iterations "
                f"without the model finishing.[/yellow]",
                title="Max iterations",
            ))

    def _chat(self, use_native: bool) -> list[dict]:
        kwargs = {"model": self.model, "messages": self.messages, "stream": True}
        if use_native:
            kwargs["tools"] = TOOL_DEFINITIONS

        collected: list[str] = []
        tool_calls: list[dict] = []
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
                    tool_calls = tcs
                    if live:
                        live.stop()
                        live = None
                if content:
                    collected.append(content)
                    if not tool_calls:
                        if live is None:
                            status.stop()
                            live = Live(console=console, refresh_per_second=20)
                            live.start()
                        live_parts.append(content)
                        live.update(Markdown("".join(live_parts)))
                if chunk.get("done"):
                    break
        finally:
            status.stop()
            if live:
                live.stop()

        full_text = "".join(collected)
        full_msg: dict = {"role": "assistant"}
        if full_text:
            full_msg["content"] = full_text
        if tool_calls and use_native:
            full_msg["tool_calls"] = tool_calls
        self.messages.append(full_msg)

        if use_native:
            if tool_calls:
                for tc in tool_calls:
                    fn = tc["function"]
                    console.print(f"  [yellow]→ {fn['name']}({json.dumps(fn.get('arguments', {}))})[/yellow]")
                return tool_calls
            return []

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
        path = args.get("path", "")
        if name == "write_file":
            preview = Syntax(args.get("content", "")[:2000], "text", theme="monokai", line_numbers=True)
            console.print(Panel(preview, title=f"write_file → {path}", border_style="yellow"))
        elif name == "edit_file":
            colored = []
            for line in args.get("diff", "").splitlines()[:80]:
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
            raise typer.Exit(0)
        if name == "write_file":
            args["content"] = Prompt.ask("New content", default=args.get("content", ""))
        elif name == "edit_file":
            args["diff"] = Prompt.ask("New diff", default=args.get("diff", ""))
        return True

    def _execute_and_record(self, call: dict) -> None:
        if "function" in call:
            name = call["function"]["name"]
            args = call["function"].get("arguments", {})
        else:
            name = call["tool"]
            args = call.get("args", {})

        if name in ("write_file", "edit_file"):
            if not self._confirm_write(name, args):
                self.messages.append({"role": "tool", "content": "[skipped] User declined the change."})
                return

        if name == "run_command":
            cmd = args.get("cmd", "")
            with Status(f"[cyan]Running: {cmd}[/cyan]", console=console, spinner="dots"):
                result = execute_tool(name, args)
        else:
            result = execute_tool(name, args)

        if name == "read_file" and not result.startswith("[error]"):
            self.files_in_context.add(args.get("path", ""))
        if name in ("write_file", "edit_file") and result.startswith("[ok]"):
            self.files_modified.add(args.get("path", ""))

        if name == "run_command" and "Exit Code: 0" not in result and not result.startswith("[error]"):
            stderr = result.split("STDERR:", 1)[1].strip() if "STDERR:" in result else result
            console.print(Panel(stderr or result, title="STDERR", border_style="red"))
        else:
            preview = result[:300] + ("…" if len(result) > 300 else "")
            console.print(Panel(preview, title=f"{name} result", border_style="green"))

        self.messages.append({"role": "tool", "content": result})

        if name == "run_command" and "Exit Code: 0" not in result and not result.startswith("[error]"):
            cmd = args.get("cmd", "")
            retries = self._cmd_retries.get(cmd, 0)
            if retries < 2:
                self._cmd_retries[cmd] = retries + 1
                self.messages.append({
                    "role": "system",
                    "content": (
                        "The command failed. Analyze the STDERR and use edit_file to fix the issue, "
                        "then try the command again."
                    ),
                })
                console.print("[yellow]Self-heal: asking model to fix and retry...[/yellow]")
            else:
                console.print(Panel(
                    f"[red]Command failed twice: {cmd}\nManual intervention required.[/red]",
                    title="Self-heal limit reached",
                ))

    def _stream_markdown(self, text: str) -> None:
        words = text.split(" ")
        collected: list[str] = []
        with Live(refresh_per_second=15, console=console) as live:
            for i, word in enumerate(words):
                collected.append(word)
                if i < len(words) - 1:
                    collected.append(" ")
                live.update(Markdown("".join(collected)))
