# ReAct — Phase 1: Agentic Tool Calling

ReAct is a local-first AI coding agent CLI. Phase 1 adds **read-only tools**
and a **tool-calling loop**: the LLM decides when to invoke a tool, the agent
executes it, feeds results back, and repeats until done.

## Prerequisites

1. **Python 3.10+** — [python.org](https://www.python.org/)
2. **Ollama** — [ollama.com](https://ollama.com)

   ```bash
   ollama serve               # start the server
   ollama pull llama3.2       # or qwen2.5-coder:7b
   ```

3. **Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

## Quick Start

```bash
# Ask the agent to read a file
python main.py "read main.py and explain its purpose"

# Ask the agent to search for a pattern
python main.py "find where the Agent class is defined"

# Specify a model
python main.py "explain how search_code works" --model llama3.2

# Run the test suite (no Ollama required — uses mocks)
python test_phase1.py
```

## Tools Available

| Tool | Description | Arguments |
|------|-------------|-----------|
| `read_file` | Read a file within the working directory | `path` (relative) |
| `search_code` | Search for a substring across source files | `query` |

**Safety**: Both tools are read-only and path-safe — paths outside the
working directory are rejected (e.g., `../../etc/passwd`).

## How It Works

```
User prompt
    │
    ▼
Agent.send(prompt + tool definitions to Ollama)
    │
    ├──► LLM returns tool_call(s) → Agent executes → result fed back → repeat
    └──► LLM returns final answer → streamed to terminal (DONE)
```

The CLI checks whether the model supports **native tool-calling** (via
`ollama show`). If yes, it passes tools through Ollama's `tools` parameter.
If not, it falls back to a **system prompt** that forces JSON output:

```json
{"tool": "read_file", "args": {"path": "main.py"}}
```

or `DONE: <final answer>` to terminate.

## TUI (Terminal UI)

```
╭── ReAct · llama3.2 ─────────────────────╮
│ read main.py and explain its purpose     │
╰─────────────────────────────────────────╯
Tool mode: native

  → read_file({"path": "main.py"})
╭── read_file result ─────────────────────╮
│ #!/usr/bin/env python3                   │
│ ... (file contents, truncated)          │
╰─────────────────────────────────────────╯
⠋ Thinking (llama3.2)  1 files in context
The file defines a Typer CLI with an Agent class.
```

- **Model name** — shown in the header panel and spinner status.
- **Files in context** — a counter that increments each time `read_file` succeeds.
- **Spinner** — a Rich `Status` spinner while the model is thinking.
- **Streaming** — final answers stream word-by-word through a Rich `Live` panel.

## Testing

```bash
python test_phase1.py
```

14 tests covering:
- **Tools**: reading files, not-found errors, traversal blocking, 50KB truncation,
  multi-extension search, empty results, `execute_tool` dispatch, broad exception handling
- **Agent loop** (mocked LLM with streaming): native tool-calling, JSON fallback,
  multi-turn (read → search → done), max-iterations cap

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `--model` / `-m` | auto-detect | Ollama model to use |
| `MAX_ITERATIONS` | 20 | Max tool-call loop iterations before stopping |
| `MAX_READ_BYTES` | 50 KB | Max file size returned by `read_file` |

## Troubleshooting

- **Connection error** — Ollama isn't running. Run `ollama serve`.
- **Model not found** — pull it: `ollama pull <model-name>`.
- **Tool mode: JSON fallback** — your model doesn't support native tools;
  the CLI auto-detected this and is using the JSON system-prompt path.
