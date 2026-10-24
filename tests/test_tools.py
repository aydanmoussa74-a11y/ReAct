"""Tests for tool implementations."""

import os
import tempfile
from pathlib import Path

import pytest

from react.tools import (
    read_file,
    search_code,
    write_file,
    edit_file,
    undo,
    run_command,
    execute_tool,
    TOOL_DEFINITIONS,
)
import react.tools as tools_mod
import react.utils as utils_mod


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    utils_mod._WORKSPACE_ROOT = tmp_path
    tools_mod._WORKSPACE_ROOT = tmp_path
    yield tmp_path


def test_read_file_success(workspace):
    (workspace / "a.py").write_text("print('hi')")
    assert "print" in read_file("a.py")


def test_read_file_traversal(workspace):
    assert read_file("../../etc/passwd").startswith("[error]")


def test_write_and_edit_and_undo(workspace):
    assert write_file("demo.txt", "hello\nworld\n").startswith("[ok]")
    diff = """--- a/demo.txt
+++ b/demo.txt
@@ -1,2 +1,2 @@
-hello
+hi
 world
"""
    assert edit_file("demo.txt", diff).startswith("[ok]")
    assert "hi" in Path("demo.txt").read_text()
    assert undo().startswith("[ok]")
    assert "hello" in Path("demo.txt").read_text()


def test_dotfile_blocked(workspace):
    assert write_file(".env", "SECRET=1").startswith("[error]")


def test_run_command_ok(workspace):
    out = run_command("echo hello")
    assert "Exit Code: 0" in out
    assert "hello" in out


def test_run_command_blocked(workspace):
    assert "Dangerous command blocked" in run_command("rm -rf /")
    assert "Dangerous command blocked" in run_command("sudo ls")


def test_run_command_failure(workspace):
    out = run_command("false")
    assert "Exit Code: 1" in out


def test_tool_definitions_schema():
    names = {td["function"]["name"] for td in TOOL_DEFINITIONS}
    assert "run_command" in names
    assert "read_file" in names
    for td in TOOL_DEFINITIONS:
        assert "parameters" in td["function"]
        assert "required" in td["function"]["parameters"]
