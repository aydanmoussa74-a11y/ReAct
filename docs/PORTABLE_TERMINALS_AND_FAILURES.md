# Portable terminal setup and troubleshooting

ReAct is a Python terminal application, not a Termux-only app. It can run in Termux, Linux/macOS terminals, and Android coding-app terminals such as Acode **when that terminal environment provides Python 3.10+, pip/venv, a POSIX shell, and interactive TTY input/output**. Acode's Alpine environment is separate from Termux; packages installed in one are not automatically available in the other.

## One command

From the repository root:

```sh
sh scripts/react.sh
```

For a fresh clone:

```sh
git clone https://github.com/aydanmoussa74-a11y/ReAct.git && cd ReAct && sh scripts/react.sh
```

For the classic interface:

```sh
sh scripts/react.sh --classic
```

The launcher finds Python 3.10+, creates a local `.venv`, installs the base project/dependencies when missing, then launches ReAct. The first run needs internet access. It cannot install Python itself or supply an API key/account credits.

## Acode (Alpine Linux environment)

Acode's terminal in the reported setup says “Welcome to Alpine Linux.” It is a separate Linux container/environment from Termux. The error `sh: can't open 'scripts/react.sh': No such file or directory` means the script is absent from the checked-out branch/folder; it is not a Python or provider error.

After the bootstrap file exists in your checkout, run it from the repository root. If Python is missing, use Alpine's package manager to install Python 3, py3-pip, and the available venv/ensurepip support, then retry. Package names and venv support depend on the Alpine image. If that environment is restricted and cannot create a venv, use a full terminal environment that supports Python venv.

## Termux

Termux has its own filesystem and packages. Installing Python in Termux does not install Python in Acode's Alpine environment, and vice versa. From a checkout containing this script, run `sh scripts/react.sh`. If you cloned the repository before this script was added, that checkout will not update automatically; update the checkout or clone it again.

## Common failures

| Message | Cause | Fix |
|---|---|---|
| `scripts/react.sh: No such file` | Checkout/branch predates the script, wrong folder, or script not tracked on that branch | Confirm repository root and update/clone a branch that contains `scripts/react.sh`. |
| Python 3.10+ required | Python missing/too old in that terminal environment | Install a compatible Python in that environment. |
| Cannot create `.venv` | venv/ensurepip unavailable or directory not writable | Install that distro's venv support or use a terminal with venv support. |
| pip network/install failure | No internet, DNS/index issue, or package unavailable for this platform | Fix network/package support and retry the same launcher command. |
| Pydantic/maturin native build error | An optional extra needs native build support not available on this Python/platform | Start with base dependencies; don't install optional extras unless needed and supported. |
| Ollama connection refused | Ollama server is not running/reachable | Start Ollama where supported, or use a hosted provider. |
| API key rejected / no credits | Key/account access or provider balance issue | Check the provider dashboard and model access. Never share or commit keys. |
| TUI display/input problems | Terminal lacks full interactive TTY/ANSI support | Try `sh scripts/react.sh --classic` or a terminal with proper TTY support. |

## Model provider notes

The launcher installs the ReAct application, not model services. Hosted models require a provider key and may require credits. Ollama requires a separately installed and running server. API requests may send prompt/code context to the selected provider; review that provider's data policies.

## Verification boundaries

Automated CI on Linux does not guarantee that every Android terminal or restricted Alpine container supports Python venv and interactive TTYs. Those platform-specific behaviors must be checked in the target terminal.
