from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from app.harness.contracts import HarnessToolContext
from app.harness.errors import HarnessExecutionError
from app.harness.registry import HarnessRegistry

DEFAULT_TIMEZONE = "Asia/Shanghai"
_WEEKDAY_NAMES_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class CurrentDatetimeArguments(BaseModel):
    """Arguments for the trusted current-time capability."""

    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Optional IANA timezone such as Asia/Shanghai. Omit it to use the "
            "current request's trusted client timezone."
        ),
    )


def current_datetime(
    context: HarnessToolContext,
    arguments: BaseModel,
) -> dict[str, object]:
    if not isinstance(arguments, CurrentDatetimeArguments):
        raise HarnessExecutionError(
            "INVALID_ARGUMENTS",
            "Handler expected CurrentDatetimeArguments.",
        )
    timezone_name = str(arguments.timezone or context.timezone or DEFAULT_TIMEZONE).strip()
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HarnessExecutionError(
            "INVALID_TIMEZONE",
            "时区无效，请使用 IANA 时区名称，例如 Asia/Shanghai。",
            details={"timezone": timezone_name},
        ) from exc

    utc_value = _utc_now()
    local_value = utc_value.astimezone(timezone)
    offset = local_value.strftime("%z")
    formatted_offset = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    weekday = local_value.isoweekday()
    return {
        "datetime": local_value.isoformat(timespec="seconds"),
        "date": local_value.date().isoformat(),
        "time": local_value.time().replace(microsecond=0).isoformat(),
        "timezone": timezone.key,
        "utc_offset": formatted_offset,
        "iso_weekday": weekday,
        "weekday_name": _WEEKDAY_NAMES_ZH[weekday - 1],
        "utc_datetime": utc_value.isoformat(timespec="seconds"),
    }


def register_time_tools(registry: HarnessRegistry) -> HarnessRegistry:
    registry.register(
        name="current_datetime",
        description=(
            "Return the trusted current date and time in an IANA timezone. Use this "
            "for requests involving today, yesterday, recent days, weeks, months, "
            "deadlines, or date ranges; do not infer the current date from model knowledge."
        ),
        argument_model=CurrentDatetimeArguments,
        handler=current_datetime,
        side_effect="read",
    )
    return registry


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DEFAULT_TIMEZONE",
    "CurrentDatetimeArguments",
    "current_datetime",
    "register_time_tools",
]
