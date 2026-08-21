from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.harness_session_cleanup import (
    harness_session_workspace_path,
    harness_task_workspace_path,
)
from app.harness.artifacts import open_harness_artifact
from app.harness.errors import HarnessExecutionError
from app.harness.workspace_files import (
    WORKSPACE_FILE_KIND_DELIVERABLE,
    WORKSPACE_FILE_VISIBILITY_SESSION,
    WORKSPACE_FILE_VISIBILITY_TASK_FRAME,
    create_workspace_file_ref,
    list_session_workspace_file_refs,
    load_workspace_file_refs,
    materialize_workspace_file_ref,
    open_workspace_file_ref,
)


def _test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _read(opened) -> bytes:
    try:
        return b"".join(opened.iter_bytes())
    finally:
        opened.close()


def test_workspace_file_ref_keeps_immutable_task_snapshot_after_source_changes(
    tmp_path: Path,
) -> None:
    workspace = (tmp_path / "task").resolve()
    source = workspace / "reports" / "source.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id,amount\nA-1,42\n", encoding="utf-8")

    with Session(_test_engine()) as db:
        file_ref = create_workspace_file_ref(
            db,
            tenant_id="tenant-demo",
            session_id="session-1",
            task_frame_id="task-1",
            workspace_root=workspace,
            source_path="reports/source.csv",
        )
        db.commit()

        source.write_text("changed", encoding="utf-8")
        restored = load_workspace_file_refs(
            db,
            tenant_id="tenant-demo",
            session_id="session-1",
            task_frame_id="task-1",
            ref_ids=[file_ref.id],
        )

    archived = _read(open_harness_artifact(workspace, file_ref.storage_path))

    assert archived == b"id,amount\nA-1,42\n"
    assert restored == [file_ref]
    assert file_ref.storage_path.startswith(".harness/files/")
    assert file_ref.model_payload()["path"] == "reports/source.csv"
    assert file_ref.visibility == WORKSPACE_FILE_VISIBILITY_TASK_FRAME


def test_workspace_file_ref_cannot_cross_taskframe_boundaries(tmp_path: Path) -> None:
    workspace = (tmp_path / "task").resolve()
    workspace.mkdir()
    (workspace / "source.txt").write_text("private", encoding="utf-8")

    with Session(_test_engine()) as db:
        file_ref = create_workspace_file_ref(
            db,
            tenant_id="tenant-demo",
            session_id="session-1",
            task_frame_id="task-1",
            workspace_root=workspace,
            source_path="source.txt",
        )
        db.commit()
        with pytest.raises(HarnessExecutionError) as exc_info:
            load_workspace_file_refs(
                db,
                tenant_id="tenant-demo",
                session_id="session-1",
                task_frame_id="task-2",
                ref_ids=[file_ref.id],
            )

    assert exc_info.value.error.code == "WORKSPACE_FILE_REF_UNAVAILABLE"


def test_session_file_ref_is_available_to_a_later_taskframe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    tenant_id = "tenant-demo"
    session_id = "session-1"
    source_workspace = harness_task_workspace_path(
        tenant_id=tenant_id,
        session_id=session_id,
        task_frame_id="task-1",
    )
    source_workspace.mkdir(parents=True)
    source = source_workspace / "reports" / "report.md"
    source.parent.mkdir()
    source.write_text("# 初版报告\n", encoding="utf-8")

    with Session(_test_engine()) as db:
        file_ref = create_workspace_file_ref(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            task_frame_id="task-1",
            workspace_root=source_workspace,
            source_path="reports/report.md",
            logical_path="作业票核查报告.md",
            kind=WORKSPACE_FILE_KIND_DELIVERABLE,
            visibility=WORKSPACE_FILE_VISIBILITY_SESSION,
        )
        db.commit()
        source.write_text("# 被修改的源文件\n", encoding="utf-8")

        later_refs = load_workspace_file_refs(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            task_frame_id="task-2",
            ref_ids=[file_ref.id],
        )
        manifest = list_session_workspace_file_refs(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        consumer_workspace = harness_task_workspace_path(
            tenant_id=tenant_id,
            session_id=session_id,
            task_frame_id="task-2",
        )
        materialized = materialize_workspace_file_ref(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            task_frame_id="task-2",
            workspace_root=consumer_workspace,
            ref_id=file_ref.id,
            session_workspace_root=harness_session_workspace_path(
                tenant_id=tenant_id,
                session_id=session_id,
            ),
        )

    assert harness_session_workspace_path(
        tenant_id=tenant_id,
        session_id=session_id,
    ).joinpath(file_ref.storage_path).is_file()
    assert _read(open_workspace_file_ref(file_ref)) == "# 初版报告\n".encode()
    assert later_refs == [file_ref]
    assert manifest == [file_ref]
    assert file_ref.model_payload()["visibility"] == "session"
    assert materialized.model_payload()["path"].startswith("input/session/")
    assert (consumer_workspace / materialized.relative_path).read_text(encoding="utf-8") == (
        "# 初版报告\n"
    )


def test_workspace_file_ref_rejects_unknown_kind(tmp_path: Path) -> None:
    workspace = (tmp_path / "task").resolve()
    workspace.mkdir()
    (workspace / "source.txt").write_text("content", encoding="utf-8")

    with Session(_test_engine()) as db, pytest.raises(HarnessExecutionError) as exc_info:
        create_workspace_file_ref(
            db,
            tenant_id="tenant-demo",
            session_id="session-1",
            task_frame_id="task-1",
            workspace_root=workspace,
            source_path="source.txt",
            kind="working",
        )

    assert exc_info.value.error.code == "WORKSPACE_FILE_KIND_INVALID"
