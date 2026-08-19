from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.harness.errors import HarnessExecutionError

TASK_INPUT_DIRECTORY = "input"
TASK_WORK_DIRECTORY = "work"
TASK_OUTPUT_DIRECTORY = "output"


@dataclass(frozen=True)
class TaskWorkspaceLayout:
    """Stable directory contract for one ordinary Agent TaskFrame."""

    root: Path
    input_dir: Path
    work_dir: Path
    output_dir: Path


def ensure_task_workspace_layout(workspace_root: Path) -> TaskWorkspaceLayout:
    """Provision TaskFrame directories without following symlinks."""

    try:
        requested_root = Path(workspace_root)
        requested_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if requested_root.is_symlink():
            raise HarnessExecutionError(
                "INVALID_WORKSPACE",
                "Harness 工作区不能使用符号链接。",
            )
        root = requested_root.resolve(strict=True)
    except OSError as exc:
        raise HarnessExecutionError("INVALID_WORKSPACE", "Harness 工作区不可用。") from exc
    if not root.is_dir() or root.is_symlink():
        raise HarnessExecutionError("INVALID_WORKSPACE", "Harness 工作区不可用。")

    directories: list[Path] = []
    for name in (TASK_INPUT_DIRECTORY, TASK_WORK_DIRECTORY, TASK_OUTPUT_DIRECTORY):
        directory = root / name
        try:
            if directory.is_symlink():
                raise HarnessExecutionError(
                    "INVALID_WORKSPACE",
                    "Harness 工作区布局目录不能使用符号链接。",
                )
            directory.mkdir(mode=0o700, exist_ok=True)
        except HarnessExecutionError:
            raise
        except OSError as exc:
            raise HarnessExecutionError(
                "INVALID_WORKSPACE",
                "无法创建 Harness 工作区布局目录。",
            ) from exc
        if not directory.is_dir() or directory.is_symlink():
            raise HarnessExecutionError("INVALID_WORKSPACE", "Harness 工作区布局目录不可用。")
        directories.append(directory.resolve(strict=True))

    return TaskWorkspaceLayout(
        root=root,
        input_dir=directories[0],
        work_dir=directories[1],
        output_dir=directories[2],
    )


__all__ = [
    "TASK_INPUT_DIRECTORY",
    "TASK_OUTPUT_DIRECTORY",
    "TASK_WORK_DIRECTORY",
    "TaskWorkspaceLayout",
    "ensure_task_workspace_layout",
]
