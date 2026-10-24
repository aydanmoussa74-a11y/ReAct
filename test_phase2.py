#!/usr/bin/env python3
"""Phase 2 demo: write/edit confirmation + undo.

This script does not require Ollama. It directly exercises the tools
and the confirmation helper by simulating a user saying "y".

Run:  python test_phase2.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import tools
from tools import write_file, edit_file, undo, execute_tool


def main() -> None:
    print("=" * 60)
    print("ReAct Phase 2 — Write tools + undo demo")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        tools._WORKSPACE_ROOT = Path(tmp)

        # 1. Create a file via write_file
        print("\n[1] write_file creates demo.txt")
        result = write_file("demo.txt", "hello world\nline two\n")
        print(f"  {result}")
        assert Path("demo.txt").read_text() == "hello world\nline two\n"

        # 2. Edit it with a unified diff
        print("\n[2] edit_file applies a unified diff")
        diff = """--- a/demo.txt
+++ b/demo.txt
@@ -1,2 +1,2 @@
-hello world
+hello ReAct
 line two
"""
        result = edit_file("demo.txt", diff)
        print(f"  {result}")
        assert "hello ReAct" in Path("demo.txt").read_text()

        # 3. Undo restores the previous version
        print("\n[3] undo restores the last snapshot")
        result = undo()
        print(f"  {result}")
        restored = Path("demo.txt").read_text()
        assert "hello world" in restored, f"Expected original content, got: {restored}"
        print("  ✅ undo restored the pre-edit content")

        # 4. Dotfile protection
        print("\n[4] Dotfile protection")
        result = write_file(".env", "SECRET=1")
        assert result.startswith("[error]"), f"Should block .env, got: {result}"
        print("  ✅ .env write blocked (use --dangerously-allow-dotfiles to override)")

        # 5. execute_tool dispatch
        print("\n[5] execute_tool routes correctly")
        result = execute_tool("write_file", {"path": "another.txt", "content": "ok"})
        assert result.startswith("[ok]")
        print("  ✅ execute_tool('write_file') works")

    print("\n" + "=" * 60)
    print("Phase 2 tools + undo demo passed! ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
