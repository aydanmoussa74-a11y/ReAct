"""ReAct agent loop with streaming, confirmation, and self-healing."""

from __future__ import annotations

import json
import re

from .ollama_compat import ollama
import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from rich.syntax import Syntax

from .tools import TOOL_DEFINITIONS, execute_tool
from .mcp_client import get_mcp_tools

console = Console()
MAX_ITERATIONS = 20

_FALLBACK_SYSTEM = (
    "You are a coding agent with tools. Output one of:\n"
    '  {"tool": "name", "args": {"arg": "value"}}  — then STOP\n'
    "  DONE: <final answer>\n"
    "Tools: get_repo_map, read_file, search_code, write_file, edit_file, undo, run_command. "
    "One call per turn.\n\n"
    "Codebase investigation protocol (Map → Investigate → Read → Trace → Plan → Change → Verify):\n"
    "Before any code change, bug fix, refactor, or new feature:\n"
    "1. If you have not yet explored the relevant parts of the codebase, call get_repo_map() first.\n"
    "2. Use search_code to locate symbols, error messages, routes, and related implementations.\n"
    "3. Use read_file to inspect the actual source of the relevant files. Never assume behavior from a filename or an AST summary.\n"
    "4. Follow important calls into related modules, configuration, and tests when the first file does not explain the full behavior.\n"
    "5. Only after you understand the current implementation and likely side effects, plan the smallest change and use write_file / edit_file.\n"
    "6. After changes, verify with run_command (tests, linters, etc.) and report exactly what was changed and what was verified.\n"
    "The repo map is only an index. Do not edit code solely from the map. If evidence is insufficient, investigate further or state the uncertainty."
)

# Native tool mode uses the same investigation and verification protocol without
# instructing the model to emit JSON tool calls as plain text.
_NATIVE_SYSTEM = _FALLBACK_SYSTEM.replace(
    'Output one of:\n'
    '  {"tool": "name", "args": {"arg": "value"}}  — then STOP\n'
    '  DONE: <final answer>\n'
    'Tools: get_repo_map, read_file, search_code, write_file, edit_file, undo, run_command. '
    'One call per turn.\n\n',
    'Use the native tool-calling interface when a tool is needed; do not emit JSON tool calls as plain text.\n'
    'Tools: get_repo_map, read_file, search_code, write_file, edit_file, undo, run_command.\n\n',
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
        system_prompt = _NATIVE_SYSTEM if use_native else _FALLBACK_SYSTEM
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = system_prompt
        else:
            self.messages.insert(0, {"role": "system", "content": system_prompt})
        self.messages.append({"role": "user", "content": prompt})

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
            # Merge local tools with any loaded MCP tools
            merged = list(TOOL_DEFINITIONS)
            for t in get_mcp_tools():
                clean = {k: v for k, v in t.items() if k != "_mcp_server"}
                merged.append(clean)
            kwargs["tools"] = merged

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

    def _confirm_command(self, args: dict) -> bool:
        cmd = str(args.get("cmd", "")).strip()
        console.print(Panel(
            f"[yellow]{cmd or '(empty command)'}[/yellow]\n"
            "Commands run with shell interpretation disabled, but can still modify files or execute programs.",
            title="Confirm command execution",
            border_style="yellow",
        ))
        choice = Prompt.ask(
            "[bold]Run this command?[/bold]",
            choices=["y", "n"],
            default="n",
            show_choices=True,
        )
        if choice != "y":
            console.print("[dim]Command skipped.[/dim]")
            return False
        return True

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
        if name == "run_command" and not self._confirm_command(args):
            self.messages.append({"role": "tool", "content": "[skipped] User declined command execution."})
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
