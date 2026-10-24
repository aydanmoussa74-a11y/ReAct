"""Tests for git utilities used by /commit."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from react.git_utils import is_git_repo, get_staged_diff, execute_commit


def test_is_git_repo_true():
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "true\n"
    with patch("react.git_utils.subprocess.run", return_value=mock):
        assert is_git_repo() is True


def test_is_git_repo_false():
    mock = MagicMock()
    mock.returncode = 128
    mock.stdout = ""
    with patch("react.git_utils.subprocess.run", return_value=mock):
        assert is_git_repo() is False


def test_get_staged_diff_empty():
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = ""
    with patch("react.git_utils.subprocess.run", return_value=mock):
        assert get_staged_diff() is None


def test_get_staged_diff_content():
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "diff --git a/foo.py b/foo.py\n+hello\n"
    with patch("react.git_utils.subprocess.run", return_value=mock):
        assert "foo.py" in (get_staged_diff() or "")


def test_execute_commit_success():
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "[main abc123] feat: add thing\n"
    mock.stderr = ""
    with patch("react.git_utils.subprocess.run", return_value=mock):
        ok, out = execute_commit("feat: add thing")
        assert ok is True
        assert "feat:" in out


def test_execute_commit_failure():
    mock = MagicMock()
    mock.returncode = 1
    mock.stdout = ""
    mock.stderr = "nothing to commit\n"
    with patch("react.git_utils.subprocess.run", return_value=mock):
        ok, out = execute_commit("chore: empty")
        assert ok is False
        assert "nothing to commit" in out
