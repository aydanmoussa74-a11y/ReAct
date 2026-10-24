"""Local model discovery and download helpers for ReAct."""

from __future__ import annotations

import subprocess

import ollama
from rich.console import Console
from rich.status import Status

console = Console()

RECOMMENDED_MODELS = [
    "qwen2.5-coder:7b",
    "llama3.2",
    "deepseek-coder:6.7b",
    "phi3:mini",
]


def get_local_models() -> list[str]:
    """Return names of models currently available in the local Ollama instance."""
    try:
        result = ollama.Client().list()
        models = result.get("models", [])
        return [m.get("model", "") for m in models if m.get("model")]
    except Exception:
        return []


def pull_model(model_name: str) -> bool:
    """Download a model via `ollama pull`. Returns True on success."""
    with Status(f"[cyan]Downloading {model_name}...[/cyan]", console=console, spinner="dots"):
        try:
            proc = subprocess.run(
                ["ollama", "pull", model_name],
                capture_output=True,
                text=True,
                timeout=600,
            )
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            console.print(f"[red]Download of {model_name} timed out.[/red]")
            return False
        except FileNotFoundError:
            console.print("[red]ollama CLI not found. Is Ollama installed?[/red]")
            return False
        except Exception as exc:
            console.print(f"[red]Failed to pull {model_name}: {exc}[/red]")
            return False
