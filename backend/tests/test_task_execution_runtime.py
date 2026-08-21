from __future__ import annotations

import os
from pathlib import Path

from app.harness import task_runtime


def _executable(path: Path, content: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_task_runtime_reuses_managed_python_and_reviewed_node(
    monkeypatch, tmp_path: Path
) -> None:
    python = _executable(tmp_path / "python-runtime" / "bin" / "python3")
    node = _executable(tmp_path / "srt-runtime" / "bin" / "node")
    cli = tmp_path / "srt-runtime" / "dist" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("// test", encoding="utf-8")
    monkeypatch.setattr(task_runtime, "_ensure_runtime_python", lambda: python)
    monkeypatch.setattr(task_runtime, "resolve_srt", lambda: (node, cli))
    task_runtime.clear_task_execution_runtime_cache()

    try:
        runtime = task_runtime.resolve_task_execution_runtime()
    finally:
        task_runtime.clear_task_execution_runtime_cache()

    path_entries = runtime.environment["PATH"].split(os.pathsep)
    assert path_entries[:2] == [str(python.parent), str(node.parent)]
    assert runtime.environment["GENERAL_SKILL_RUNTIME_PYTHON"] == str(python)
    assert runtime.environment["GENERAL_SKILL_RUNTIME_NODE"] == str(node)
    assert runtime.environment["VIRTUAL_ENV"] == str(python.parent.parent)
    assert runtime.readonly_roots == (python.parent.parent, node.parent.parent)


def test_task_runtime_keeps_logical_venv_path_for_python_alias(
    monkeypatch, tmp_path: Path
) -> None:
    base_python = _executable(tmp_path / "base" / "bin" / "python3")
    venv_python = tmp_path / "venv" / "bin" / "python3"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(base_python)
    monkeypatch.setattr(task_runtime, "_ensure_runtime_python", lambda: venv_python)
    monkeypatch.setattr(task_runtime, "resolve_srt", lambda: None)
    monkeypatch.setattr(task_runtime.shutil, "which", lambda _name: None)
    task_runtime.clear_task_execution_runtime_cache()

    try:
        runtime = task_runtime.resolve_task_execution_runtime()
    finally:
        task_runtime.clear_task_execution_runtime_cache()

    assert runtime.python == venv_python
    assert runtime.environment["PATH"].split(os.pathsep)[0] == str(venv_python.parent)
    assert runtime.readonly_roots == (venv_python.parent.parent, base_python.parent.parent)
