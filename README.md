# ReAct

Local-first AI coding agent that runs against Ollama.

It can read files, search code, write or edit files (with confirmation), run shell commands, and automatically try to fix failures.

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.10+ and a running Ollama instance (`ollama serve`).

## Usage

### One-shot

```bash
python -m react.cli "explain the Agent class"
# or after pip install -e .
react "create a notes.md summarizing this project"
```

### Interactive REPL

Run with no arguments to enter a persistent session. Conversation history and file context are kept across turns.

```bash
react
# or
python -m react.cli
```

```
react> explain the Agent class
react> now add a docstring to the run method
react> /undo
react> /clear
react> /exit
```

**Slash commands**

| Command | Action |
|---------|--------|
| `/help` | Show available commands |
| `/model` | List recommended models and local status |
| `/model <name>` | Switch to (and optionally download) a model |
| `/undo` | Restore the most recent snapshot |
| `/clear` | Clear conversation history (workspace unchanged) |
| `/exit`, `/quit` | Exit the REPL |

Ctrl+C during generation cancels the current turn and returns to the prompt.

### Model switching

`/model` shows recommended models and whether they are already downloaded.
`/model <name>` switches the active model immediately if it is local.
If it is not local, ReAct asks whether to download it, then switches after a successful pull.

### Flags

- `--model` / `-m` — Ollama model (default: auto-detect llama3.2 or qwen2.5-coder)
- `--dangerously-allow-dotfiles` — permit writes to hidden files (use carefully)

## Tools

| Tool | Description |
|------|-------------|
| `get_repo_map` | Structural map of the project (filtered paths + Python class/function names) |
| `read_file` | Read a file (50 KB truncation) |
| `search_code` | Substring search across source files |
| `write_file` | Overwrite a file (confirmation required) |
| `edit_file` | Apply a unified diff (confirmation required) |
| `undo` | Restore the most recent snapshot |
| `run_command` | Run a shell command (30 s timeout, dangerous prefixes blocked) |

### Repo Map

`get_repo_map` returns a compact, deterministic tree of the current workspace:

- Hidden paths and common build/cache directories are ignored (`__pycache__`, `node_modules`, `.venv`, `dist`, `build`, etc.).
- Python files include top-level class and function names (extracted with the standard `ast` module) and optional line counts.
- Non-Python files are listed by path only.
- Hard limit of 500 files; larger repositories return a warning and suggest using `search_code`.

The map is only an index. The agent is instructed to follow Map → Investigate → Read → Trace → Plan → Change → Verify: call the map first on unfamiliar codebases, then use `search_code` and `read_file` to inspect the actual source before proposing or applying changes. Verification uses `run_command`. The map does not guarantee correctness or eliminate the need to read code.

### Safety

- All file operations are confined to the current working directory.
- Dotfiles are refused unless `--dangerously-allow-dotfiles` is set.
- Every write/edit is snapshotted to `~/.react/snapshots/` before the change.
- `run_command` blocks prefixes such as `rm -rf`, `sudo`, `dd`, `mkfs`, `wget`, `curl`.
- Commands have a hard 30-second timeout.

### Confirmation

Before any write or edit the CLI shows a preview and asks:

```
Apply this change? [y/n/e/a]
```

### Self-healing

If `run_command` returns a non-zero exit code the agent is automatically told to analyze the error, use `edit_file` to fix the code, and retry. The same command is auto-retried at most twice; after that the loop stops and asks for manual intervention.

## Development

```bash
pytest tests/
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ITERATIONS` | 20 | Hard stop for the agent loop |
| `MAX_READ_BYTES` | 50 KB | Truncation limit for `read_file` |
