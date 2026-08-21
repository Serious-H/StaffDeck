from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.harness import (
    HarnessExecutor,
    HarnessRegistry,
    HarnessToolCall,
    HarnessToolContext,
    register_time_tools,
)
from app.harness import time as time_module


def _execute(
    tmp_path: Path,
    arguments: dict[str, object],
    *,
    timezone: str = "Asia/Shanghai",
):
    registry = register_time_tools(HarnessRegistry())
    context = HarnessToolContext(
        run_id="time-test",
        workspace_root=tmp_path.resolve(),
        timezone=timezone,
    )
    return HarnessExecutor(registry).execute(
        context,
        HarnessToolCall(
            call_id="time-call",
            name="current_datetime",
            arguments=arguments,
        ),
    )


def test_time_registry_exposes_trusted_read_capability() -> None:
    registry = register_time_tools(HarnessRegistry())

    assert registry.names() == ("current_datetime",)
    registered = registry.get("current_datetime")
    assert registered is not None
    assert registered.spec.side_effect == "read"
    assert registered.spec.input_schema["additionalProperties"] is False


def test_current_datetime_uses_request_timezone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        time_module,
        "_utc_now",
        lambda: datetime(2026, 8, 20, 16, 30, tzinfo=UTC),
    )

    result = _execute(tmp_path, {})

    assert result.success is True
    assert result.data == {
        "datetime": "2026-08-21T00:30:00+08:00",
        "date": "2026-08-21",
        "time": "00:30:00",
        "timezone": "Asia/Shanghai",
        "utc_offset": "+08:00",
        "iso_weekday": 5,
        "weekday_name": "星期五",
        "utc_datetime": "2026-08-20T16:30:00+00:00",
    }


def test_current_datetime_accepts_explicit_timezone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        time_module,
        "_utc_now",
        lambda: datetime(2026, 8, 21, 0, 0, tzinfo=UTC),
    )

    result = _execute(tmp_path, {"timezone": "UTC"})

    assert result.success is True
    assert result.data is not None
    assert result.data["datetime"] == "2026-08-21T00:00:00+00:00"
    assert result.data["timezone"] == "UTC"


def test_current_datetime_rejects_invalid_timezone(tmp_path: Path) -> None:
    result = _execute(tmp_path, {"timezone": "Mars/Olympus"})

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "INVALID_TIMEZONE"
