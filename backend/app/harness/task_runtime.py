from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.harness.errors import HarnessExecutionError
from app.harness.sandbox import resolve_srt

_SYSTEM_PATH_ENTRIES = (
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/sbin",
    "/usr/bin",
    "/sbin",
    "/bin",
)


@dataclass(frozen=True)
class TaskExecutionRuntime:
    """Shared, administrator-controlled toolchain exposed to one TaskFrame."""

    python: Path
    node: Path | None
    environment: dict[str, str]
    readonly_roots: tuple[Path, ...]


@lru_cache(maxsize=1)
def resolve_task_execution_runtime() -> TaskExecutionRuntime:
    """Resolve the existing GeneralSkill Python plus the reviewed Node runtime.

    GeneralSkill packages now execute through native Harness tools instead of a
    second generated runner. Reuse the old runner's managed Python contract so
    ``python`` and ``python3`` no longer depend on an interactive shell, Conda,
    or the host distribution's default interpreter.
    """

    try:
        python = Path(os.path.abspath(_ensure_runtime_python().expanduser()))
        resolved_python = python.resolve(strict=True)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise HarnessExecutionError(
            "TASK_RUNTIME_UNAVAILABLE",
            "StaffDeck 任务 Python 运行环境不可用。",
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not resolved_python.is_file() or not os.access(resolved_python, os.X_OK):
        raise HarnessExecutionError(
            "TASK_RUNTIME_UNAVAILABLE",
            "StaffDeck 任务 Python 解释器不可执行。",
        )

    node = _resolve_node_runtime()
    optional_node_paths = [node.parent] if node is not None else []
    path_entries = _stable_unique_paths(
        [python.parent, *optional_node_paths, *map(Path, _SYSTEM_PATH_ENTRIES)]
    )
    environment = {
        "PATH": os.pathsep.join(str(path) for path in path_entries),
        "VIRTUAL_ENV": str(python.parent.parent),
        "GENERAL_SKILL_RUNTIME_PYTHON": str(python),
        "PYTHONUNBUFFERED": "1",
    }
    if node is not None:
        environment["GENERAL_SKILL_RUNTIME_NODE"] = str(node)

    executables = [python]
    if node is not None:
        executables.append(node)
    readonly_roots = _stable_unique_paths(
        root
        for executable in executables
        for root in _runtime_roots(executable)
        if not _is_system_runtime_path(root)
    )
    return TaskExecutionRuntime(
        python=python,
        node=node,
        environment=environment,
        readonly_roots=tuple(readonly_roots),
    )


def clear_task_execution_runtime_cache() -> None:
    resolve_task_execution_runtime.cache_clear()


def _resolve_node_runtime() -> Path | None:
    resolved_srt = resolve_srt()
    candidate = resolved_srt[0] if resolved_srt is not None else None
    if candidate is None:
        raw = shutil.which("node")
        candidate = Path(raw) if raw else None
    if candidate is None:
        return None
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return resolved


def _ensure_runtime_python() -> Path:
    # Import lazily: app.general_skills.__init__ keeps the legacy runner
    # available, and that runner imports harness.command. Importing it while
    # harness.command itself is initializing would create a package cycle.
    from app.general_skills.runtime_env import ensure_runtime_python

    return ensure_runtime_python()


def _runtime_roots(executable: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in (executable, executable.resolve()):
        if len(candidate.parents) >= 2:
            root = candidate.parent.parent
            if root.is_dir():
                roots.append(root)
    return tuple(roots)


def _is_system_runtime_path(path: Path) -> bool:
    system_roots = map(Path, ("/usr", "/bin", "/sbin", "/lib", "/lib64"))
    return any(path == root or path.is_relative_to(root) for root in system_roots)


def _stable_unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidate = Path(path)
        marker = str(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(candidate)
    return result


__all__ = [
    "TaskExecutionRuntime",
    "clear_task_execution_runtime_cache",
    "resolve_task_execution_runtime",
]
