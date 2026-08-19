from __future__ import annotations

from pathlib import Path

from app.harness import (
    HarnessExecutor,
    HarnessToolCall,
    HarnessToolContext,
    build_file_tool_registry,
)
from app.harness.workspace_layout import ensure_task_workspace_layout


def _execute(
    context: HarnessToolContext,
    name: str,
    arguments: dict[str, object],
):
    return HarnessExecutor(build_file_tool_registry()).execute(
        context,
        HarnessToolCall(call_id=f"call-{name}", name=name, arguments=arguments),
    )


def test_taskframe_layout_makes_inputs_read_only_and_outputs_publishable(
    tmp_path: Path,
) -> None:
    workspace = (tmp_path / "task").resolve()
    layout = ensure_task_workspace_layout(workspace)
    (layout.input_dir / "source.txt").write_text("source", encoding="utf-8")
    context = HarnessToolContext(
        run_id="run-layout",
        workspace_root=workspace,
        enforce_task_workspace_layout=True,
    )

    read_input = _execute(context, "read_file", {"path": "input/source.txt"})
    denied_write = _execute(
        context,
        "write_file",
        {"path": "input/source.txt", "content": "changed"},
    )
    work_write = _execute(
        context,
        "write_file",
        {"path": "work/plan.md", "content": "draft", "create_parents": True},
    )
    output_write = _execute(
        context,
        "write_file",
        {"path": "output/report.md", "content": "final", "create_parents": True},
    )
    denied_publish = _execute(
        context,
        "publish_artifact",
        {"path": "work/plan.md"},
    )
    published = _execute(
        context,
        "publish_artifact",
        {"path": "output/report.md"},
    )

    assert read_input.success is True
    assert read_input.data and read_input.data["content"] == "source"
    assert denied_write.success is False
    assert denied_write.error and denied_write.error.code == "WORKSPACE_PATH_SCOPE_DENIED"
    assert work_write.success is True
    assert output_write.success is True
    assert denied_publish.success is False
    assert denied_publish.error and denied_publish.error.code == "WORKSPACE_PATH_SCOPE_DENIED"
    assert published.success is True
    assert published.data and published.data["path"] == "output/report.md"


def test_taskframe_layout_hides_harness_internal_directory_from_root_listing(
    tmp_path: Path,
) -> None:
    workspace = (tmp_path / "task").resolve()
    ensure_task_workspace_layout(workspace)
    internal = workspace / ".harness" / "tool-results"
    internal.mkdir(parents=True)
    (internal / "result.json").write_text("{}", encoding="utf-8")
    context = HarnessToolContext(
        run_id="run-listing",
        workspace_root=workspace,
        enforce_task_workspace_layout=True,
    )

    listed = _execute(context, "list_directory", {"path": "."})

    assert listed.success is True
    assert listed.data
    assert {entry["path"] for entry in listed.data["entries"]} == {
        "input",
        "output",
        "work",
    }
