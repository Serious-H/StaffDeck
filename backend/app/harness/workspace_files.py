from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from app.core.harness_session_cleanup import (
    harness_session_workspace_path,
    harness_task_workspace_path,
)
from app.db.models import HarnessWorkspaceFileRecord, new_id
from app.harness.artifacts import (
    HarnessArtifactAccessError,
    normalize_harness_artifact_path,
    open_harness_artifact,
)
from app.harness.errors import HarnessExecutionError
from app.harness.workspace_layout import ensure_task_workspace_layout

# This store deliberately lives beside the other Harness implementation details
# (tool results and materialized skill packages), rather than becoming a user
# addressable workspace directory.
WORKSPACE_INTERNAL_DIRECTORY = ".harness"
WORKSPACE_FILE_STORE_DIRECTORY = f"{WORKSPACE_INTERNAL_DIRECTORY}/files"
MAX_WORKSPACE_FILE_REF_BYTES = 50 * 1024 * 1024

WORKSPACE_FILE_VISIBILITY_TASK_FRAME = "task_frame"
WORKSPACE_FILE_VISIBILITY_SESSION = "session"
_WORKSPACE_FILE_VISIBILITIES = {
    WORKSPACE_FILE_VISIBILITY_TASK_FRAME,
    WORKSPACE_FILE_VISIBILITY_SESSION,
}

WORKSPACE_FILE_KIND_SOURCE = "source"
WORKSPACE_FILE_KIND_DERIVED = "derived"
WORKSPACE_FILE_KIND_INTERNAL = "internal"
WORKSPACE_FILE_KIND_DELIVERABLE = "deliverable"
_WORKSPACE_FILE_KINDS = {
    WORKSPACE_FILE_KIND_SOURCE,
    WORKSPACE_FILE_KIND_DERIVED,
    WORKSPACE_FILE_KIND_INTERNAL,
    WORKSPACE_FILE_KIND_DELIVERABLE,
}


@dataclass(frozen=True)
class WorkspaceFileRef:
    """A trusted immutable file handle scoped to one Harness session.

    A ref stores identity and provenance, never a caller-provided absolute
    filesystem path. Future tasks can therefore request a verified snapshot
    without gaining access to a producer TaskFrame's mutable directory.
    """

    id: str
    tenant_id: str
    session_id: str
    task_frame_id: str
    logical_path: str
    storage_path: str
    sha256: str
    size: int
    content_type: str
    kind: str
    visibility: str
    producer_invocation_id: str | None = None

    @classmethod
    def from_record(cls, record: HarnessWorkspaceFileRecord) -> WorkspaceFileRef:
        return cls(
            id=record.id,
            tenant_id=record.tenant_id,
            session_id=record.session_id,
            task_frame_id=record.task_frame_id,
            logical_path=record.logical_path,
            storage_path=record.storage_path,
            sha256=record.sha256,
            size=record.size,
            content_type=record.content_type,
            kind=record.kind,
            visibility=record.visibility,
            producer_invocation_id=record.producer_invocation_id,
        )

    def model_payload(self) -> dict[str, Any]:
        """Return only safe ref metadata for model-facing task context."""

        return {
            "kind": "workspace_file_ref",
            "ref_id": self.id,
            "task_frame_id": self.task_frame_id,
            "path": self.logical_path,
            "sha256": self.sha256,
            "size": self.size,
            "content_type": self.content_type,
            "file_kind": self.kind,
            "visibility": self.visibility,
            "producer_invocation_id": self.producer_invocation_id,
        }


@dataclass(frozen=True)
class MaterializedWorkspaceFile:
    """A verified immutable ref copied into one consumer TaskFrame input."""

    file_ref: WorkspaceFileRef
    relative_path: str

    def model_payload(self) -> dict[str, Any]:
        return {
            "kind": "materialized_workspace_file",
            "ref_id": self.file_ref.id,
            "path": self.relative_path,
            "sha256": self.file_ref.sha256,
            "size": self.file_ref.size,
            "content_type": self.file_ref.content_type,
            "file_kind": self.file_ref.kind,
        }


def create_workspace_file_ref(
    db: Session,
    *,
    tenant_id: str,
    session_id: str,
    task_frame_id: str,
    workspace_root: Path,
    source_path: str,
    logical_path: str | None = None,
    kind: str = WORKSPACE_FILE_KIND_INTERNAL,
    visibility: str = WORKSPACE_FILE_VISIBILITY_TASK_FRAME,
    archive_workspace_root: Path | None = None,
    producer_invocation_id: str | None = None,
) -> WorkspaceFileRef:
    """Archive one verified workspace file and register its immutable ref.

    Session-visible refs are stored under the session workspace by default;
    task-local refs remain in the producer TaskFrame.  The latter is useful
    for a future dependency protocol, but only session-visible refs can be
    listed by later turns.
    """

    normalized_source = _normalize_path(source_path, field="source")
    normalized_logical = _normalize_path(
        logical_path or normalized_source,
        field="logical",
    )
    normalized_visibility = str(visibility or "").strip()
    if normalized_visibility not in _WORKSPACE_FILE_VISIBILITIES:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_VISIBILITY_INVALID",
            "工作区文件可见性无效。",
        )
    normalized_kind = str(kind or "").strip()
    if normalized_kind not in _WORKSPACE_FILE_KINDS:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_KIND_INVALID",
            "工作区文件类型无效。",
        )

    if archive_workspace_root is None:
        archive_workspace_root = (
            harness_session_workspace_path(
                tenant_id=tenant_id,
                session_id=session_id,
            )
            if normalized_visibility == WORKSPACE_FILE_VISIBILITY_SESSION
            else workspace_root
        )
    archive = _archive_workspace_file(
        workspace_root,
        normalized_source,
        archive_workspace_root=archive_workspace_root,
    )
    record = HarnessWorkspaceFileRecord(
        id=new_id("hwfile"),
        tenant_id=tenant_id,
        session_id=session_id,
        task_frame_id=task_frame_id,
        logical_path=normalized_logical,
        storage_path=archive.storage_path,
        sha256=archive.sha256,
        size=archive.size,
        content_type=(
            mimetypes.guess_type(normalized_logical)[0]
            or "application/octet-stream"
        ),
        kind=normalized_kind,
        visibility=normalized_visibility,
        producer_invocation_id=producer_invocation_id,
    )
    db.add(record)
    db.flush()
    return WorkspaceFileRef.from_record(record)


def load_workspace_file_refs(
    db: Session,
    *,
    tenant_id: str,
    session_id: str,
    task_frame_id: str,
    ref_ids: Iterable[str],
) -> list[WorkspaceFileRef]:
    """Load refs in caller order and fail closed on scope mismatches."""

    ordered_ids = [str(value).strip() for value in ref_ids]
    if not ordered_ids or any(not value for value in ordered_ids):
        raise HarnessExecutionError(
            "WORKSPACE_FILE_REF_INVALID",
            "工作区文件引用不能为空。",
        )
    if len(ordered_ids) != len(set(ordered_ids)):
        raise HarnessExecutionError(
            "WORKSPACE_FILE_REF_INVALID",
            "工作区文件引用不能重复。",
        )

    task_frame_condition = and_(
        HarnessWorkspaceFileRecord.visibility == WORKSPACE_FILE_VISIBILITY_TASK_FRAME,
        HarnessWorkspaceFileRecord.task_frame_id == task_frame_id,
    )
    session_condition = (
        HarnessWorkspaceFileRecord.visibility == WORKSPACE_FILE_VISIBILITY_SESSION
    )
    rows = db.exec(
        select(HarnessWorkspaceFileRecord).where(
            HarnessWorkspaceFileRecord.tenant_id == tenant_id,
            HarnessWorkspaceFileRecord.session_id == session_id,
            or_(task_frame_condition, session_condition),
            HarnessWorkspaceFileRecord.id.in_(ordered_ids),
        )
    ).all()
    by_id = {row.id: row for row in rows}
    missing = [ref_id for ref_id in ordered_ids if ref_id not in by_id]
    if missing:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_REF_UNAVAILABLE",
            "工作区文件引用不存在、已失效，或不属于当前会话任务范围。",
            details={"missing_ref_ids": missing[:10]},
        )
    return [WorkspaceFileRef.from_record(by_id[ref_id]) for ref_id in ordered_ids]


def list_session_workspace_file_refs(
    db: Session,
    *,
    tenant_id: str,
    session_id: str,
    limit: int = 100,
) -> list[WorkspaceFileRef]:
    """Return durable session-visible files in creation order."""

    bounded_limit = max(1, min(int(limit), 200))
    rows = db.exec(
        select(HarnessWorkspaceFileRecord)
        .where(
            HarnessWorkspaceFileRecord.tenant_id == tenant_id,
            HarnessWorkspaceFileRecord.session_id == session_id,
            HarnessWorkspaceFileRecord.visibility == WORKSPACE_FILE_VISIBILITY_SESSION,
        )
        .order_by(HarnessWorkspaceFileRecord.created_at.asc())
        .limit(bounded_limit)
    ).all()
    return [WorkspaceFileRef.from_record(row) for row in rows]


def open_workspace_file_ref(
    file_ref: WorkspaceFileRef,
    *,
    task_workspace_root: Path | None = None,
    session_workspace_root: Path | None = None,
):
    """Open a ref from its immutable task or session archive."""

    if file_ref.visibility == WORKSPACE_FILE_VISIBILITY_SESSION:
        root = session_workspace_root or harness_session_workspace_path(
            tenant_id=file_ref.tenant_id,
            session_id=file_ref.session_id,
        )
    elif file_ref.visibility == WORKSPACE_FILE_VISIBILITY_TASK_FRAME:
        root = task_workspace_root or harness_task_workspace_path(
            tenant_id=file_ref.tenant_id,
            session_id=file_ref.session_id,
            task_frame_id=file_ref.task_frame_id,
        )
    else:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_VISIBILITY_INVALID",
            "工作区文件引用的可见性无效。",
        )
    return open_harness_artifact(_workspace_root(root), file_ref.storage_path)


def materialize_workspace_file_ref(
    db: Session,
    *,
    tenant_id: str,
    session_id: str,
    task_frame_id: str,
    workspace_root: Path,
    ref_id: str,
    session_workspace_root: Path | None = None,
    input_directory: str = "session",
) -> MaterializedWorkspaceFile:
    """Copy one authorized immutable ref into ``input/session`` for this task.

    The consumer never receives the session archive path. The copied snapshot
    has a deterministic name and read-only mode, so repeated requests are
    idempotent and scripts can use an ordinary `/workspace/input/...` path.
    """

    [file_ref] = load_workspace_file_refs(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        task_frame_id=task_frame_id,
        ref_ids=[ref_id],
    )
    normalized_input_directory = str(input_directory or "").strip()
    if normalized_input_directory not in {"session", "dependencies"}:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_MATERIALIZATION_FAILED",
            "工作区文件输入目录无效。",
        )
    layout = ensure_task_workspace_layout(workspace_root)
    filename = PurePosixPath(file_ref.logical_path).name or "file"
    relative_path = f"input/{normalized_input_directory}/{file_ref.id}-{filename}"
    destination = layout.root.joinpath(*PurePosixPath(relative_path).parts)
    _ensure_materialization_parent(layout.root, destination.parent)
    if destination.exists():
        _verify_materialized_file(
            layout.root,
            relative_path,
            expected_digest=file_ref.sha256,
            expected_size=file_ref.size,
        )
        return MaterializedWorkspaceFile(file_ref=file_ref, relative_path=relative_path)

    opened = open_workspace_file_ref(
        file_ref,
        task_workspace_root=layout.root,
        session_workspace_root=session_workspace_root,
    )
    try:
        _copy_materialized_file(
            opened,
            destination,
            expected_digest=file_ref.sha256,
        )
    finally:
        opened.close()
    _verify_materialized_file(
        layout.root,
        relative_path,
        expected_digest=file_ref.sha256,
        expected_size=file_ref.size,
    )
    return MaterializedWorkspaceFile(file_ref=file_ref, relative_path=relative_path)


@dataclass(frozen=True)
class _ArchivedFile:
    storage_path: str
    sha256: str
    size: int


def _normalize_path(value: str, *, field: str) -> str:
    try:
        return normalize_harness_artifact_path(value)
    except HarnessArtifactAccessError as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_PATH_INVALID",
            f"工作区文件{field}路径无效。",
        ) from exc


def _archive_workspace_file(
    workspace_root: Path,
    source_path: str,
    *,
    archive_workspace_root: Path,
) -> _ArchivedFile:
    source_root = _workspace_root(workspace_root)
    archive_root = _workspace_root(archive_workspace_root)
    try:
        opened = open_harness_artifact(source_root, source_path)
    except HarnessArtifactAccessError as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_SOURCE_UNAVAILABLE",
            "无法安全读取待归档的工作区文件。",
        ) from exc
    try:
        if opened.size > MAX_WORKSPACE_FILE_REF_BYTES:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_REF_TOO_LARGE",
                "工作区文件超过可传递文件的大小限制。",
                details={
                    "actual_bytes": opened.size,
                    "max_bytes": MAX_WORKSPACE_FILE_REF_BYTES,
                },
            )
        digest = opened.sha256()
        store = _ensure_file_store(archive_root)
        destination = store / digest
        if destination.exists():
            _verify_stored_file(archive_root, digest, expected_size=opened.size)
        else:
            _copy_opened_file(opened, destination, expected_digest=digest)
            _verify_stored_file(archive_root, digest, expected_size=opened.size)
        return _ArchivedFile(
            storage_path=f"{WORKSPACE_FILE_STORE_DIRECTORY}/{digest}",
            sha256=digest,
            size=opened.size,
        )
    finally:
        opened.close()


def _workspace_root(workspace_root: Path) -> Path:
    root = Path(workspace_root)
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise HarnessExecutionError("INVALID_WORKSPACE", "Harness 工作区不可用。") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise HarnessExecutionError("INVALID_WORKSPACE", "Harness 工作区不可用。")
    return resolved


def _ensure_file_store(root: Path) -> Path:
    internal = root / WORKSPACE_INTERNAL_DIRECTORY
    store = internal / "files"
    for directory in (internal, store):
        try:
            if directory.is_symlink():
                raise HarnessExecutionError(
                    "INVALID_WORKSPACE",
                    "Harness 内部文件存储不能使用符号链接。",
                )
            directory.mkdir(mode=0o700, exist_ok=True)
            if not directory.is_dir() or directory.is_symlink():
                raise HarnessExecutionError(
                    "INVALID_WORKSPACE",
                    "Harness 内部文件存储不可用。",
                )
        except HarnessExecutionError:
            raise
        except OSError as exc:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_STORE_UNAVAILABLE",
                "无法创建工作区文件存储。",
            ) from exc
    return store


def _verify_stored_file(root: Path, digest: str, *, expected_size: int) -> None:
    try:
        opened = open_harness_artifact(
            root,
            f"{WORKSPACE_FILE_STORE_DIRECTORY}/{digest}",
        )
    except HarnessArtifactAccessError as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_STORE_UNAVAILABLE",
            "工作区文件存储中的已有文件不可安全读取。",
        ) from exc
    try:
        if opened.size != expected_size or opened.sha256() != digest:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_STORE_CORRUPT",
                "工作区文件存储校验失败。",
            )
    finally:
        opened.close()


def _copy_opened_file(
    opened: Any,
    destination: Path,
    *,
    expected_digest: str,
) -> None:
    descriptor = None
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".file-", dir=str(destination.parent))
        temporary_path = Path(raw_path)
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            for block in opened.iter_bytes():
                handle.write(block)
                digest.update(block)
            handle.flush()
            os.fsync(handle.fileno())
        if digest.hexdigest() != expected_digest:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_CHANGED",
                "工作区文件在登记过程中发生变化。",
            )
        os.chmod(temporary_path, 0o400)
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
        else:
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
    except HarnessExecutionError:
        raise
    except OSError as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_STORE_UNAVAILABLE",
            "无法归档工作区文件。",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _ensure_materialization_parent(root: Path, directory: Path) -> None:
    try:
        relative = directory.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_MATERIALIZATION_FAILED",
            "工作区文件输入目录无效。",
        ) from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise HarnessExecutionError(
                    "WORKSPACE_FILE_MATERIALIZATION_FAILED",
                    "工作区文件输入目录不能使用符号链接。",
                )
            current.mkdir(mode=0o700, exist_ok=True)
            if not current.is_dir() or current.is_symlink():
                raise HarnessExecutionError(
                    "WORKSPACE_FILE_MATERIALIZATION_FAILED",
                    "工作区文件输入目录不可用。",
                )
        except HarnessExecutionError:
            raise
        except OSError as exc:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_MATERIALIZATION_FAILED",
                "无法创建工作区文件输入目录。",
            ) from exc


def _copy_materialized_file(
    opened: Any,
    destination: Path,
    *,
    expected_digest: str,
) -> None:
    descriptor = None
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".input-", dir=str(destination.parent))
        temporary_path = Path(raw_path)
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            for block in opened.iter_bytes():
                handle.write(block)
                digest.update(block)
            handle.flush()
            os.fsync(handle.fileno())
        if digest.hexdigest() != expected_digest:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_STORE_CORRUPT",
                "会话归档文件校验失败。",
            )
        os.chmod(temporary_path, 0o400)
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
        else:
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
    except HarnessExecutionError:
        raise
    except OSError as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_MATERIALIZATION_FAILED",
            "无法将会话文件物化到当前任务输入目录。",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _verify_materialized_file(
    workspace_root: Path,
    relative_path: str,
    *,
    expected_digest: str,
    expected_size: int,
) -> None:
    try:
        opened = open_harness_artifact(workspace_root, relative_path)
    except HarnessArtifactAccessError as exc:
        raise HarnessExecutionError(
            "WORKSPACE_FILE_MATERIALIZATION_FAILED",
            "当前任务输入文件不可安全读取。",
        ) from exc
    try:
        if opened.size != expected_size or opened.sha256() != expected_digest:
            raise HarnessExecutionError(
                "WORKSPACE_FILE_MATERIALIZATION_FAILED",
                "当前任务输入文件校验失败。",
            )
    finally:
        opened.close()


__all__ = [
    "MAX_WORKSPACE_FILE_REF_BYTES",
    "WORKSPACE_FILE_KIND_DELIVERABLE",
    "WORKSPACE_FILE_KIND_DERIVED",
    "WORKSPACE_FILE_KIND_INTERNAL",
    "WORKSPACE_FILE_KIND_SOURCE",
    "WORKSPACE_FILE_VISIBILITY_SESSION",
    "WORKSPACE_FILE_VISIBILITY_TASK_FRAME",
    "MaterializedWorkspaceFile",
    "WorkspaceFileRef",
    "create_workspace_file_ref",
    "list_session_workspace_file_refs",
    "load_workspace_file_refs",
    "materialize_workspace_file_ref",
    "open_workspace_file_ref",
]
