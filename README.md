# ReAct — Phase 1 + Phase 2

ReAct is a local-first AI coding agent CLI.

**Phase 1**: read-only tools (`read_file`, `search_code`) + tool-calling loop.  
**Phase 2**: write tools (`write_file`, `edit_file`) with human confirmation, snapshots, and `undo`.

## Prerequisites

1. **Python 3.10+**
2. **Ollama** — `ollama serve` then `ollama pull llama3.2` (or any model with tool support)
3. Dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Quick Start

```bash
# Phase 1 style — read and search
python main.py "read main.py and explain the Agent class"

# Phase 2 — the agent can propose writes (you confirm)
python main.py "create a file called notes.md with a short summary of this project"

# Allow writes to dotfiles (use carefully)
python main.py "update .env with a new key" --dangerously-allow-dotfiles

# Run tests
python test_phase1.py
python test_phase2.py
```

## Tools

| Tool | Description | Confirmation |
|------|-------------|--------------|
| `read_file` | Read a file (50 KB truncation) | No |
| `search_code` | Substring search across source files | No |
| `write_file` | Overwrite a file with full content | Yes |
| `edit_file` | Apply a unified diff | Yes |
| `undo` | Restore the most recent snapshot | No |

**Safety**
- All paths are confined to the current working directory.
- Dotfiles (`.env`, `.git/*`, etc.) are refused unless you pass `--dangerously-allow-dotfiles`.
- Every write/edit is snapshotted to `~/.react/snapshots/{timestamp}/` before the change.
- `edit_file` validates the diff; if it cannot be applied, the tool returns a clear error so the model can retry.

## Confirmation Flow

Before any `write_file` or `edit_file`, the CLI shows a Rich preview (green additions / red deletions) and prompts:

```
Apply this change? [y/n/e/a]:
```

- **y** — apply
- **n** — skip (agent continues)
- **e** — edit the proposed content/diff before applying
- **a** — abort the whole run

## Context Tracker

The status line now shows:

```
Thinking (llama3.2)  3 files in context · 1 modified
```

- "files in context" = set of files successfully read
- "modified" = set of files written/edited in this session

## Snapshots & Undo

Before every mutation the original file is copied to:

```
~/.react/snapshots/YYYYMMDD-HHMMSS-ffffff/<relative-path>
```

`undo` restores the most recent snapshot.

## Configuration

| Flag / Setting | Default | Description |
|----------------|---------|-------------|
| `--model` / `-m` | auto | Ollama model |
| `--dangerously-allow-dotfiles` | off | Permit writes to hidden files |
| `MAX_ITERATIONS` | 20 | Hard stop for the agent loop |

## Troubleshooting

- **Connection error** — run `ollama serve`
- **Tool mode: JSON fallback** — model does not advertise native tools; the system prompt path is used
- **Diff failed to apply** — the model produced a bad unified diff; it can retry
- **Dotfile blocked** — add `--dangerously-allow-dotfiles` if you really mean it
