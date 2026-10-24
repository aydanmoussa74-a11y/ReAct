"""Tests for repository mapping and tool registration."""

from pathlib import Path

import pytest

from react.repo_map import generate_repo_map
from react.tools import TOOL_DEFINITIONS, execute_tool
import react.tools as tools_mod
import react.utils as utils_mod


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    utils_mod._WORKSPACE_ROOT = tmp_path
    tools_mod._WORKSPACE_ROOT = tmp_path
    yield tmp_path


def test_nested_tree_and_python_symbols(workspace):
    (workspace / "src").mkdir()
    (workspace / "src" / "agent.py").write_text(
        "class Agent:\n    def run(self):\n        pass\n\nasync def execute():\n    pass\n"
    )
    (workspace / "src" / "tools.py").write_text("def read_file():\n    pass\n")
    (workspace / "README.md").write_text("# hi\n")

    result = generate_repo_map(workspace)
    assert "src/" in result
    assert "agent.py" in result
    assert "class Agent" in result
    # run is nested inside the class; only top-level symbols are extracted
    assert "def run" not in result
    assert "async def execute" in result
    assert "tools.py" in result
    assert "def read_file" in result
    assert "README.md" in result
    # Deterministic: directories appear before their files
    assert result.index("src/") < result.index("agent.py")


def test_syntax_error_still_listed(workspace):
    (workspace / "bad.py").write_text("def broken(:\n")
    result = generate_repo_map(workspace)
    assert "bad.py" in result
    # No symbols extracted, but file is present
    assert "def " not in result or "class " not in result


def test_ignores_hidden_and_cache(workspace):
    (workspace / ".hidden").mkdir()
    (workspace / ".hidden" / "secret.py").write_text("x = 1\n")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "pkg").mkdir()
    (workspace / "node_modules" / "pkg" / "index.js").write_text("//")
    (workspace / "real.py").write_text("def ok():\n    pass\n")

    result = generate_repo_map(workspace)
    assert "real.py" in result
    assert ".hidden" not in result
    assert "__pycache__" not in result
    assert "node_modules" not in result


def test_line_counts(workspace):
    (workspace / "a.py").write_text("x = 1\ny = 2\n")
    result = generate_repo_map(workspace)
    assert "a.py" in result
    assert "lines" in result


def test_file_limit_warning(workspace, monkeypatch):
    # Create more than 500 files
    for i in range(501):
        (workspace / f"f{i}.txt").write_text("x")
    result = generate_repo_map(workspace)
    assert result.startswith("[warning] Repo is too large")
    assert "search_code" in result


def test_symlink_escape_ignored(workspace):
    outside = workspace.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.py").write_text("x = 1\n")
    link = workspace / "link.py"
    try:
        link.symlink_to(outside / "secret.py")
    except OSError:
        pytest.skip("symlink not supported")
    result = generate_repo_map(workspace)
    assert "secret.py" not in result


def test_tool_registered_and_executable(workspace):
    (workspace / "hello.py").write_text("def greet():\n    pass\n")
    names = {td["function"]["name"] for td in TOOL_DEFINITIONS}
    assert "get_repo_map" in names
    out = execute_tool("get_repo_map", {})
    assert "hello.py" in out
    assert "def greet" in out


def test_system_prompt_mentions_map():
    from react.agent import _FALLBACK_SYSTEM
    assert "get_repo_map" in _FALLBACK_SYSTEM
    assert "read_file" in _FALLBACK_SYSTEM
    assert "Map" in _FALLBACK_SYSTEM or "investigation" in _FALLBACK_SYSTEM.lower()
