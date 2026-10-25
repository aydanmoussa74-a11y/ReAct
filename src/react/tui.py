"""Full-screen Textual interface for ReAct.

This first TUI milestone is intentionally provider-independent. It provides the
workspace shell and local command/context discovery without pretending that an
AI turn ran before the agent event bridge is implemented.
"""
from __future__ import annotations

from pathlib import Path
import threading

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Footer, Input, RichLog, Static

AMBER = "#ffbd59"
MUTED = "#a1a1aa"
COMMANDS = [
    ("/help", "Show commands"),
    ("/status", "Show interface/provider status"),
    ("/clear", "Clear conversation display"),
    ("/connect", "Show provider configuration"),
    ("/model", "Show active model"),
    ("/approve", "Approve the pending write/command"),
    ("/deny", "Deny the pending write/command"),
    ("/exit", "Close ReAct"),
]

class ApprovalRequested(Message):
    """UI-thread message for an agent action that needs user approval."""

    def __init__(self, name: str, args: dict, decision: threading.Event, result: dict):
        super().__init__()
        self.name = name
        self.args = args
        self.decision = decision
        self.result = result


def project_files(root: Path, limit: int = 80) -> list[str]:
    """Return a bounded list of project-relative files, excluding noisy folders."""
    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", "dist", "build"}
    results: list[str] = []
    try:
        for path in root.rglob("*"):
            if any(part in ignored for part in path.parts):
                continue
            if path.is_file():
                results.append(path.relative_to(root).as_posix())
                if len(results) >= limit:
                    break
    except OSError:
        return []
    return sorted(results)


class ReActTUI(App):
    TITLE = "ReAct"
    SUB_TITLE = "Engineering workspace"

    CSS = """
    Screen { background: #0b0d10; color: #e5e7eb; }
    #topbar {
        height: 3; background: #14171c; border-bottom: solid #34302a;
        padding: 0 1; align: left middle;
    }
    #brand { width: 1fr; color: #ffbd59; text-style: bold; content-align: left middle; }
    #connection { width: auto; color: #a1a1aa; content-align: right middle; }
    #workspace { height: 1fr; }
    #sidebar {
        width: 25; min-width: 20; background: #101216;
        border-right: solid #292d34; padding: 1;
    }
    .section-label { color: #ffbd59; text-style: bold; margin-top: 1; margin-bottom: 1; }
    .side-item { color: #a1a1aa; margin-bottom: 1; }
    #main { width: 1fr; padding: 0 1; }
    #conversation-title {
        height: 3; color: #f4f4f5; text-style: bold;
        content-align: left middle; border-bottom: solid #292d34;
    }
    #welcome {
        height: auto; padding: 1 0 2 0; color: #a1a1aa;
    }
    #conversation { height: 1fr; border: none; background: #0b0d10; padding: 1; }
    #suggestions {
        height: auto; max-height: 6; display: none; color: #a1a1aa;
        background: #14171c; border-left: thick #ffbd59; padding: 0 1;
    }
    #input-area { height: auto; padding: 1 0; border-top: solid #34302a; }
    #prompt-label { color: #ffbd59; height: 1; text-style: bold; }
    #command-input { height: 3; border: solid #62503a; background: #14171c; }
    #command-input:focus { border: solid #ffbd59; }
    #hint { height: 2; color: #71717a; padding-top: 1; }
    Footer { background: #17191e; color: #a1a1aa; }
    """

    BINDINGS = [
        ("ctrl+l", "clear_chat", "Clear"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.agent = None
        self.provider = "unconfigured"
        self.model = "unresolved"
        self.use_native = False
        self.busy = False
        self.pending_approval = None
        self.last_error = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("◆  ReAct", id="brand")
            yield Static("●  LOCAL UI", id="connection")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Static("WORKSPACE", classes="section-label")
                yield Static("›  Current session", classes="side-item")
                yield Static("   Agent workspace", classes="side-item")
                yield Static("   Tool activity", classes="side-item")
                yield Static("   Approvals", classes="side-item")
                yield Static("─" * 17, classes="side-item")
                yield Static("PROJECT", classes="section-label")
                yield Static(Path.cwd().name or "Current folder", classes="side-item")
                yield Static("Context via @", classes="side-item")
                yield Static("─" * 17, classes="side-item")
                yield Static("PROVIDER", classes="section-label")
                yield Static("Detecting on first request", classes="side-item", id="provider-sidebar")
                yield Static("No API call on startup", classes="side-item")
            with Vertical(id="main"):
                yield Static("New session  /  ReAct", id="conversation-title")
                yield Static(
                    "BUILD WITH INTENT\n"
                    "Inspect the code. Plan the change. Review the evidence. Keep control.\n\n"
                    "Describe a task to start the agent. Use @path/to/file.py to include file context.",
                    id="welcome",
                )
                yield RichLog(id="conversation", wrap=True, markup=False)
                yield Static(id="suggestions")
                with Vertical(id="input-area"):
                    yield Static("MESSAGE REACT", id="prompt-label")
                    yield Input(placeholder="Describe what you want to build...", id="command-input")
                    yield Static("Enter: submit  •  / commands  •  @file context  •  /approve or /deny", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_layout()
        self.query_one("#command-input", Input).focus()
        self.query_one("#conversation", RichLog).write(Text("Ready. Provider initializes when you submit your first task.", style=MUTED))

    def on_resize(self, event) -> None:
        self._apply_layout()

    def _apply_layout(self) -> None:
        # Keep the welcome content stable across resizes; only collapse the sidebar.
        self.query_one("#sidebar").display = self.size.width >= 90

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        panel = self.query_one("#suggestions", Static)
        if value.startswith("/"):
            matches = [(cmd, desc) for cmd, desc in COMMANDS if cmd.startswith(value.split()[0])]
            if matches:
                panel.update("   ".join(cmd for cmd, _ in matches[:3]))
                panel.display = True
                return
        if "@" in value:
            token = value.rsplit("@", 1)[-1].split()[0]
            files = [name for name in project_files(Path.cwd()) if token.lower() in name.lower()][:5]
            if files:
                panel.update("PROJECT CONTEXT\n" + "\n".join("@" + name for name in files))
                panel.display = True
                return
            panel.update("PROJECT CONTEXT\nNo matching project files found.")
            panel.display = True
            return
        panel.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        self.query_one("#suggestions", Static).display = False
        if not value:
            return
        log = self.query_one("#conversation", RichLog)
        self.query_one("#welcome").display = False
        log.write(Text(f"\nYOU  ›  {value}", style="bold white"))
        if value in ("/exit", "/quit"):
            self._deny_pending()
            self.exit()
        elif value == "/help":
            log.write(Text("\n".join(f"{cmd:<10} {desc}" for cmd, desc in COMMANDS), style=AMBER))
        elif value == "/clear":
            if self.busy:
                self._append_log("Wait for the current task to finish before clearing history.")
                return
            if self.agent:
                self.agent.messages.clear()
                self.agent.files_in_context.clear()
                self.agent.files_modified.clear()
                self.agent._cmd_retries.clear()
            log.clear()
            self._append_log("Conversation and agent history cleared.")
        elif value == "/status":
            self._append_log(f"Agent: {'busy' if self.busy else 'ready'}\nProvider: {self.provider}\nModel: {self.model}\nTool mode: {'native' if self.use_native else 'JSON fallback'}\nPending approval: {'yes' if self.pending_approval else 'no'}")
        elif value == "/connect":
            self._append_log("Provider uses REACT_PROVIDER=ollama or openrouter. OpenRouter needs OPENROUTER_API_KEY and optionally REACT_MODEL before launch. This UI never displays or stores your API key.")
        elif value.startswith("/model"):
            self._append_log(f"Active model: {self.model}. Runtime switching is not available yet; use the classic CLI to change it.")
        elif value == "/approve":
            self._decide_approval(True)
        elif value == "/deny":
            self._decide_approval(False)
        elif value.startswith("/"):
            self._append_log("Unknown command. Type /help.")
        elif self.pending_approval is not None:
            self._append_log("Resolve the pending approval with /approve or /deny first.", AMBER)
        elif self.busy:
            self._append_log("Agent is still working. Wait for this turn to finish.", AMBER)
        else:
            prompt, note = self._expand_file_context(value)
            if note:
                self._append_log(note, AMBER)
            self._start_agent(prompt)
        log.scroll_end(animate=False)

    def _expand_file_context(self, prompt: str) -> tuple[str, str]:
        root = Path.cwd().resolve()
        included, notes = [], []
        refs = [p[1:].strip(".,:;!?()[]{}") for p in prompt.split() if p.startswith("@")]
        for ref in refs:
            candidate = (root / ref).resolve()
            if candidate != root and root in candidate.parents and candidate.is_file():
                try:
                    if candidate.stat().st_size > 50 * 1024:
                        notes.append(f"@{ref} skipped: file exceeds 50 KB")
                        continue
                    included.append(f"--- FILE: {ref} ---\n{candidate.read_text(encoding='utf-8')}\n--- END FILE ---")
                except (OSError, UnicodeDecodeError) as exc:
                    notes.append(f"@{ref} could not be read: {exc}")
            else:
                notes.append(f"@{ref} not found or outside project")
        if included:
            prompt += "\n\nUser-referenced project context (read-only):\n" + "\n\n".join(included)
            notes.append(f"Included {len(included)} file(s) in model prompt")
        return prompt, " • ".join(notes)

    def _start_agent(self, prompt: str) -> None:
        self.busy = True
        self.last_error = None
        self.query_one("#connection", Static).update("● WORKING")
        self.query_one("#prompt-label", Static).update("AGENT WORKING")
        self.run_worker(self._agent_turn, prompt, thread=True, exclusive=True, name="react-agent-turn")

    def _agent_turn(self, prompt: str) -> None:
        try:
            from .agent import Agent
            from .cli import _model_supports_tools, _resolve_model
            from .providers import get_provider_name
            provider = get_provider_name()
            model = _resolve_model(None, provider)
            native = _model_supports_tools(model, provider)
            self.provider, self.model, self.use_native = provider, model, native
            if self.agent is None or self.agent.provider != provider or self.agent.model != model:
                self.agent = Agent(model, provider=provider, on_event=self._agent_event, approve=self._request_approval)
            else:
                self.agent.on_event = self._agent_event
                self.agent.approve = self._request_approval
            self.call_from_thread(self._set_provider_status, provider, model, native)
            self.agent.run(prompt, use_native=native)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.call_from_thread(self._append_log, f"Agent error: {self.last_error}", "bold red")
        finally:
            self.call_from_thread(self._finish_turn)

    def _agent_event(self, event: str, data: dict) -> None:
        self.call_from_thread(self._render_agent_event, event, data)

    def _render_agent_event(self, event: str, data: dict) -> None:
        if event == "status":
            self._append_log(" • " + str(data.get("message", "")))
        elif event == "assistant_delta":
            self.query_one("#conversation", RichLog).write(Text(str(data.get("text", "")), style="white"))
        elif event == "assistant_message":
            text = str(data.get("text", "")).strip()
            if text:
                self._append_log("REACT › " + text, "white")
        elif event == "tool_call":
            args = str(data.get("args", {}))
            self._append_log(f"⚙ {data.get('name')} {args[:180]}", AMBER)
        elif event == "tool_started":
            self._append_log(f"Running {data.get('name')}…", AMBER)
        elif event == "tool_result":
            result = str(data.get("result", ""))
            self._append_log(f"Result · {data.get('name')}\n{result[:700]}")
        elif event == "approval_denied":
            self._append_log(f"Denied · {data.get('name')}", AMBER)
        elif event == "error":
            self._append_log("Agent warning: " + str(data.get("message", "")), "bold red")
        self.query_one("#conversation", RichLog).scroll_end(animate=False)

    def _request_approval(self, name: str, args: dict) -> bool:
        decision = threading.Event()
        result = {"approved": False}
        request = ApprovalRequested(name, args, decision, result)
        self.call_from_thread(self.post_message, request)
        decided = decision.wait(timeout=180)
        if not decided:
            self.call_from_thread(self._clear_expired_approval, request)
            return False
        return bool(result["approved"])

    def on_approval_requested(self, event: ApprovalRequested) -> None:
        if self.pending_approval is not None:
            event.decision.set()
            return
        self.pending_approval = event
        args = event.args
        if event.name == "write_file":
            detail = f"Path: {args.get('path', '')}\nContent:\n{str(args.get('content', ''))[:1000]}"
        elif event.name == "edit_file":
            detail = f"Path: {args.get('path', '')}\nDiff:\n{str(args.get('diff', ''))[:1000]}"
        else:
            detail = f"Command: {args.get('cmd', '')}\nCommands may run programs or modify files."
        self._append_log("APPROVAL REQUIRED — review before allowing:\n" + detail + "\nType /approve or /deny. Timeout defaults to deny.", "bold yellow")
        self.query_one("#prompt-label", Static).update("APPROVAL REQUIRED · /approve or /deny")

    def _clear_expired_approval(self, request: ApprovalRequested) -> None:
        if self.pending_approval is request:
            self.pending_approval = None
            self._append_log("Approval timed out; action was denied.", "bold yellow")
            self.query_one("#prompt-label", Static).update("AGENT WORKING")

    def _decide_approval(self, approved: bool) -> None:
        request = self.pending_approval
        if request is None:
            self._append_log("No pending approval.")
            return
        request.result["approved"] = approved
        request.decision.set()
        self.pending_approval = None
        self._append_log(("Approved: " if approved else "Denied: ") + request.name, "bold green" if approved else "bold yellow")
        self.query_one("#prompt-label", Static).update("AGENT WORKING")

    def _deny_pending(self) -> None:
        if self.pending_approval is not None:
            self._decide_approval(False)

    def _set_provider_status(self, provider: str, model: str, native: bool) -> None:
        self.query_one("#connection", Static).update("● CONNECTED")
        self.query_one("#provider-sidebar", Static).update(f"{provider} · {model}")
        self._append_log(f"Provider: {provider} · Model: {model} · Tool mode: {'native' if native else 'JSON fallback'}")

    def _finish_turn(self) -> None:
        self.busy = False
        self.query_one("#connection", Static).update("● ERROR" if self.last_error else "● READY")
        self.query_one("#prompt-label", Static).update("MESSAGE REACT")
        self.query_one("#command-input", Input).focus()

    def _append_log(self, message: str, style: str = MUTED) -> None:
        self.query_one("#conversation", RichLog).write(Text(message, style=style))

    def action_clear_chat(self) -> None:
        if self.busy:
            self._append_log("Wait for the current task to finish before clearing.")
            return
        log = self.query_one("#conversation", RichLog)
        log.clear()
        self.query_one("#welcome").display = True

    def action_quit(self) -> None:
        self._deny_pending()
        self.exit()


if __name__ == "__main__":
    ReActTUI().run()
