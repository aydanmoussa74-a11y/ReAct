# ReAct

A phone-friendly AI coding agent with a local Ollama option and OpenRouter BYOK cloud access.

It can read files, search code, write or edit files (with confirmation), run shell commands, and automatically try to fix failures.

## Install and run

Requires Python 3.10+ and an interactive terminal. Recommended one-command setup from the repository root:

```sh
sh scripts/react.sh
```

For a fresh clone, use:

```sh
git clone https://github.com/aydanmoussa74-a11y/ReAct.git && cd ReAct && sh scripts/react.sh
```

The launcher creates a project-local virtual environment, installs the base dependencies when needed, and starts ReAct. Use `sh scripts/react.sh --classic` for the classic interface. It works in Termux, Linux/macOS, and Acode-like terminal environments only when the environment provides Python 3.10+, shell, venv support, and interactive terminal I/O. See [Portable terminals and troubleshooting](docs/PORTABLE_TERMINALS_AND_FAILURES.md).

Requires Python 3.10+. Choose a provider: Ollama for a reachable local server, or OpenRouter BYOK for cloud models without downloading model weights.

## Provider setup

ReAct supports four provider choices:

| Provider | Environment variables | Default model | Notes |
|---|---|---|---|
| Ollama | `REACT_PROVIDER=ollama` (default), optional `OLLAMA_HOST` | `llama3.2` | Requires a separately running, reachable Ollama server. The Python client is not the server. |
| Gemini | `REACT_PROVIDER=gemini`, `GEMINI_API_KEY` | `gemini-2.5-flash` | Google Gemini API; standard-library HTTP, no extra SDK. |
| OpenAI | `REACT_PROVIDER=openai`, `OPENAI_API_KEY` | `gpt-4.1-mini` | OpenAI API; standard-library HTTP, no extra SDK. |
| OpenRouter | `REACT_PROVIDER=openrouter`, `OPENROUTER_API_KEY` | `openrouter/auto` | OpenRouter's OpenAI-compatible API. |

Cloud providers use ReAct's JSON-tool fallback mode: the model must follow the instructions to emit a JSON tool call or `DONE:` final answer. Native provider tool calling is not enabled in these adapters yet. API usage, quota, and billing depend on your provider/account; a key does not guarantee free usage.

### Gemini (good first option to try)

1. Create a key at https://aistudio.google.com/.
2. In the terminal, select Gemini and enter the key without saving it in the repository:

   ```sh
   export REACT_PROVIDER=gemini
   read -s -p 'Gemini API key: ' GEMINI_API_KEY; echo
   export GEMINI_API_KEY
   # Optional model override:
   export REACT_MODEL=gemini-2.5-flash
   sh scripts/react.sh
   ```

### OpenAI

Create an API key at https://platform.openai.com/api-keys, then:

```sh
export REACT_PROVIDER=openai
read -s -p 'OpenAI API key: ' OPENAI_API_KEY; echo
export OPENAI_API_KEY
export REACT_MODEL=gpt-4.1-mini
sh scripts/react.sh
```

### OpenRouter

1. Create a key at https://openrouter.ai/keys.
2. Configure it in the current shell:

   ```sh
   export REACT_PROVIDER=openrouter
   read -s -p 'OpenRouter API key: ' OPENROUTER_API_KEY; echo
   export OPENROUTER_API_KEY
   export REACT_MODEL=openrouter/auto
   sh scripts/react.sh
   ```

Choose a model ID from https://openrouter.ai/models.

These commands avoid typing the key directly into the command history, but the key remains available in that terminal session's environment. Never paste it into chat, source code, screenshots, or commits. To switch providers, set the corresponding `REACT_PROVIDER` and key variable in the same terminal. Provider selection and environment variables are per terminal/session; Acode and Termux do not automatically share them.

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
| `/commit` | Generate and apply a Conventional Commit from staged changes |
| `/mcp status` | Show connected MCP servers and tools |
| `/mcp reload` | Reload MCP config and reconnect |
| `/undo` | Restore the most recent snapshot |
| `/clear` | Clear conversation history (workspace unchanged) |
| `/exit`, `/quit` | Exit the REPL |

Ctrl+C during generation cancels the current turn and returns to the prompt.

### Model switching

`/model` shows recommended models and whether they are already downloaded.
`/model <name>` switches the active model immediately if it is local.
If it is not local, ReAct asks whether to download it, then switches after a successful pull.

### /commit

`/commit` inspects staged changes and proposes a Conventional Commit message:

1. Verifies the current directory is a git repository.
2. If nothing is staged, offers to run `git add .`.
3. Sends the staged diff to the active model with a strict prompt asking for a single Conventional Commit message.
4. Shows the proposal in a panel and asks `[y]es [n]o [e]dit`.
5. On confirmation, runs `git commit -m "..."` and displays the result.

The flow is blocking and interactive, matching the write/edit confirmation style. Empty diffs are never sent to the model.

### Flags

- `--model` / `-m` — model ID for the selected provider (Ollama model name or OpenRouter model ID)
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

## Extending ReAct with MCP

ReAct can load tools from external MCP servers (stdio transport).

Create `~/.react/mcp_config.json`:

```json
{
  "mcpServers": {
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
```

In the REPL:

- `/mcp status` — show connected servers and the tools they expose
- `/mcp reload` — re-read the config and reconnect

MCP tools are merged with ReAct’s built-in tools and routed automatically. If the `mcp` package is missing or a server fails to start, ReAct continues with local tools only.

## Development

```bash
pytest tests/
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ITERATIONS` | 20 | Hard stop for the agent loop |
| `MAX_READ_BYTES` | 50 KB | Truncation limit for `read_file` |


## Testing from Android (Termux + Acode)

Acode is useful for editing and browsing the source; run Python commands in Termux.

1. Install Git and Python in Termux:

   ```sh
   pkg update
   pkg install git python
   ```

2. Clone and enter the repository:

   ```sh
   git clone https://github.com/aydanmoussa74-a11y/ReAct.git
   cd ReAct
   ```

3. Install the project and test dependencies:

   ```sh
   python -m pip install -e ".[dev]"
   python -m pytest -q
   ```

4. Check the CLI interface:

   ```sh
   react --help
   ```

The test suite does not need a model server. On Android/Termux, select OpenRouter BYOK using the environment variables above to avoid requiring a local Ollama runtime. This uses the internet and may incur API charges. Alternatively, use a reachable Ollama server. Never expose an unauthenticated Ollama endpoint to the public internet.

Command execution is deliberately confirmed in the interactive agent. Commands run without shell interpretation, high-risk executables are blocked, and command output is capped; this is a safety improvement, not a complete operating-system sandbox.
