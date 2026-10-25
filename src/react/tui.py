"""Full-screen Textual interface for ReAct.

This first TUI milestone is intentionally provider-independent. It provides the
workspace shell and local command/context discovery without pretending that an
AI turn ran before the agent event bridge is implemented.
"""
from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

AMBER = "#ffbd59"
MUTED = "#a1a1aa"
COMMANDS = [
    ("/help", "Show commands"),
    ("/status", "Show interface/provider status"),
    ("/clear", "Clear conversation display"),
    ("/connect", "Provider setup (not implemented in TUI yet)"),
    ("/model", "Model selection (not implemented in TUI yet)"),
    ("/exit", "Close ReAct"),
]


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
                yield Static("Not connected in TUI", classes="side-item")
                yield Static("No API call on startup", classes="side-item")
            with Vertical(id="main"):
                yield Static("New session  /  ReAct", id="conversation-title")
                yield Static(
                    "BUILD WITH INTENT\n"
                    "Inspect the code. Plan the change. Review the evidence. Keep control.\n\n"
                    "Type / to explore workspace commands, or @ to reference project files.",
                    id="welcome",
                )
                yield RichLog(id="conversation", wrap=True, markup=False)
                yield Static(id="suggestions")
                with Vertical(id="input-area"):
                    yield Static("MESSAGE REACT", id="prompt-label")
                    yield Input(placeholder="Describe what you want to build...", id="command-input")
                    yield Static("Enter: submit  •  / commands  •  @ project context  •  Ctrl+L: clear", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_layout()
        self.query_one("#command-input", Input).focus()
        self.query_one("#conversation", RichLog).write(
            Text("Agent execution is not connected to this screen yet. No response will be simulated.", style=MUTED)
        )

    def on_resize(self, event) -> None:
        self._apply_layout()

    def _apply_layout(self) -> None:
        self.query_one("#sidebar").display = self.size.width >= 90
        self.query_one("#welcome").display = self.query_one("#conversation", RichLog).lines == 0

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        panel = self.query_one("#suggestions", Static)
        if value.startswith("/"):
            matches = [(cmd, desc) for cmd, desc in COMMANDS if cmd.startswith(value.split()[0])]
            if matches:
                panel.update("\n".join(f"{cmd:<12} {desc}" for cmd, desc in matches[:5]))
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

        if value == "/exit" or value == "/quit":
            self.exit()
        elif value == "/help":
            log.write(Text("\n".join(f"{cmd:<12} {desc}" for cmd, desc in COMMANDS), style=AMBER))
        elif value == "/clear":
            log.clear()
            log.write(Text("Conversation display cleared.", style=MUTED))
        elif value == "/status":
            log.write(Text(
                "UI: running\nProvider: not connected in this TUI milestone\n"
                "Agent bridge: not implemented yet\nNetwork request: none",
                style=MUTED,
            ))
        elif value.startswith("/"):
            log.write(Text("This command is not implemented in the TUI yet. Use /help.", style=MUTED))
        else:
            refs = [part[1:].strip(".,:;!?()[]{}") for part in value.split() if part.startswith("@")]
            if refs:
                root = Path.cwd().resolve()
                found = []
                for ref in refs:
                    candidate = (root / ref).resolve()
                    if candidate == root or root in candidate.parents:
                        if candidate.is_file():
                            found.append(ref)
                log.write(Text(
                    "Context references found: " + (", ".join("@" + item for item in found) if found else "none"),
                    style=AMBER if found else MUTED,
                ))
            log.write(Text(
                "Captured by the interface only. The agent bridge is the next integration step; "
                "no AI response has been fabricated.",
                style=MUTED,
            ))
        log.scroll_end(animate=False)

    def action_clear_chat(self) -> None:
        log = self.query_one("#conversation", RichLog)
        log.clear()
        self.query_one("#welcome").display = True


if __name__ == "__main__":
    ReActTUI().run()
