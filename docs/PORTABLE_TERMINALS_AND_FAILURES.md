# Portable terminals, one-command setup, and troubleshooting

ReAct is a Python CLI/TUI application, not a Termux-only app. It is designed to run in terminals that provide Python 3.10+, pip/venv support, a working terminal (TTY), and network access when using a hosted model. This includes Termux, Linux/macOS terminals, and terminal environments embedded in coding apps such as Acode when they provide those prerequisites. A terminal app by itself does not guarantee that Python, virtual environments, or all operating-system features are available.

## The one-command bootstrap

From the ReAct repository root, run:

```sh
sh scripts/react.sh
```

That command:
1. finds Python 3.10 or newer;
2. creates a project-local `.venv` if needed;
3. installs ReAct and its required dependencies if missing;
4. starts the full-screen TUI.

Use the classic interface with:

```sh
sh scripts/react.sh --classic
```

You do not need to manually run separate pip install commands for the basic TUI. The first launch needs internet access to install packages. The bootstrap installs the base dependencies only; optional integrations are not installed automatically because they may pull platform-specific dependencies.

### What the one command cannot do for you

No installer can create a model-provider account, invent an API key, grant paid credits, or start a remote service on your behalf. On first launch, type `/connect` in the TUI and choose a provider. Enter a key you obtained from that provider, select/confirm a model, and use **Test & Connect**. A successful test proves that provider returned a response; it does not guarantee that every agent tool call or every model feature is supported.

For local Ollama, the Ollama server must already be installed and running and the chosen model must be available. Installing ReAct's Python package does not install or start the Ollama server.

## Supported environment baseline

- Python 3.10 or newer.
- A terminal that supports interactive text UI input and output.
- Permission to create files in the repository (for `.venv` and ReAct's workspace features).
- Internet access for initial package installation and hosted APIs.
- Git is recommended for projects using ReAct's git-aware tools.

The bootstrap is POSIX shell. Run it with `sh scripts/react.sh`; executable-bit preservation is not required. If your terminal app does not provide a POSIX shell, Python, or venv support, use its documented package manager or a compatible terminal environment.

## Running in different terminals

### Termux on Android

Install Python and Git using Termux's package manager, clone the repository, change into its directory, then run `sh scripts/react.sh`. If Python is a very new Android build and pip reports that a dependency needs unsupported native compilation, do not install every optional extra. The base TUI is deliberately installed without the optional MCP dependency group.

### Acode or another Android coding app

Open the repository folder in the app and use its integrated terminal only if it provides Python 3.10+, shell, pip, and venv. From the repository root, run `sh scripts/react.sh`. If the app's terminal is a restricted sandbox or has no Python, use a separate Android terminal that supports those requirements; the project itself does not depend on Acode-specific APIs.

### Linux, macOS, or another desktop terminal

Ensure Python 3.10+ and venv support are installed, open a terminal in the repository root, then run `sh scripts/react.sh`. On systems with multiple Python versions, the bootstrap selects `python3` first, then `python`, provided it is 3.10+.

### Classic REPL

Use `sh scripts/react.sh --classic` to launch the legacy Rich interface instead of the full-screen Textual interface.

## Failure log and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `Python 3.10 or newer` message | Python missing or too old | Install Python 3.10+ in the terminal environment and retry. |
| `Could not create .venv` | Python lacks venv/ensurepip support or directory permissions | Install the terminal's venv support if available, check repository write permissions, and retry. |
| pip cannot download packages | Network, DNS, certificate, or package index problem | Restore internet access and retry the same bootstrap command. |
| `externally-managed-environment` | System Python prevents global installs | The bootstrap uses a project-local virtual environment; verify venv creation works and do not force a system-wide pip install. |
| Pydantic/maturin/native build failure on Android or a new Python | An optional dependency requires a native wheel/build not supported by that platform/Python | Use the base bootstrap; avoid installing `.[ai,mcp]` unless that platform supports their dependencies. |
| `Ollama support requires pip install -e '.[ai]'` | Ollama Python client extra is not installed in the active environment | Use a hosted provider through `/connect`, or install the `ai` extra only if your Python/platform can install it. A local Ollama server is also required. |
| Connection refused to Ollama port 11434 | Ollama server is not running or not reachable from this environment | Start Ollama where supported and verify the terminal can reach its server, or use a hosted provider. |
| API key rejected (401/403) | Wrong key, disabled key, or account/model access issue | Reopen the provider's official key page, create/verify the key, then reconnect. Never share the key in chat or commits. |
| Insufficient balance/credits (402) | Provider account lacks usable credits or billing | Check the provider's account limits. Choose a provider/model you can access; don't assume an API has a free tier. |
| Model not found / bad request | Default model ID changed or is not enabled for the account | In `/connect`, enter a currently supported model ID from that provider's model list/docs. |
| TUI cannot render or input is broken | Terminal lacks full TTY/ANSI support or is too constrained | Try the classic interface with `sh scripts/react.sh --classic`, or use a terminal with interactive TTY support. |
| Agent responds but tools are not used reliably | Provider/model may not support ReAct's JSON-tool fallback or context requirements | Choose a capable model and treat provider-native tool calling as unsupported unless explicitly implemented and tested. |
| Key disappears after restart | Expected session-only behavior | Run `/connect` again. Keys are not persisted to disk by the wizard. |

## Security and cost

- Never commit API keys or paste them into public issues, screenshots, or chat.
- The wizard masks key input and does not save it to a ReAct configuration file. Keys remain in the current process environment while the app runs.
- Hosted provider requests send prompts/code context to that provider. Review the provider's privacy and retention terms before using it with private repositories.
- Connection tests and agent turns may incur charges. Check the provider's current prices and account limits.
- ReAct's tool approvals and filesystem boundaries are separate from provider connectivity; review proposed writes and commands before approving them.

## Verification status

The repository's GitHub Actions matrix checks supported CPython versions on Linux. That is useful automated coverage, but it does not prove compatibility with every Android terminal, Acode's particular terminal configuration, every provider, or every model. Those environments require platform-specific runtime smoke tests.
