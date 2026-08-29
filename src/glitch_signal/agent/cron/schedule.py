"""Next-run computation for the three schedule kinds (AGENT-CRON).

Pure functions over a `schedule` dict + a reference time — no I/O, so they unit-test trivially.

    at    {at: ISO-8601}                      one-shot; no "next" after it fires
    every {every_ms, anchor_ms?}              fixed interval; anchored so cadence doesn't drift
    cron  {cron_expr, tz?}                     5/6-field cron in an IANA tz (default UTC)
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_first_run(schedule: dict, kind: str, *, now: datetime) -> datetime | None:
    """The initial next_run_at when a job is created."""
    if kind == "at":
        return _parse_iso(str(schedule["at"]))
    if kind == "every":
        anchor_ms = schedule.get("anchor_ms")
        if anchor_ms:
            return datetime.fromtimestamp(int(anchor_ms) / 1000, tz=timezone.utc)
        return now
    if kind == "cron":
        return compute_next(schedule, kind, now=now)
    raise ValueError(f"unknown schedule kind: {kind!r}")


def compute_next(schedule: dict, kind: str, *, now: datetime) -> datetime | None:
    """The next fire strictly after `now`. Returns None for a spent one-shot (`at`)."""
    if kind == "at":
        return None  # one-shot: nothing after it fires
    if kind == "every":
        every_ms = int(schedule["every_ms"])
        if every_ms <= 0:
            raise ValueError("every_ms must be positive")
        anchor_ms = schedule.get("anchor_ms")
        anchor = (datetime.fromtimestamp(int(anchor_ms) / 1000, tz=timezone.utc)
                  if anchor_ms else now)
        # advance from the anchor by whole intervals until strictly after now (no drift)
        elapsed_ms = (now - anchor).total_seconds() * 1000
        steps = int(elapsed_ms // every_ms) + 1
        return anchor + _ms(every_ms * steps)
    if kind == "cron":
        from croniter import croniter

        tz = ZoneInfo(schedule["tz"]) if schedule.get("tz") else timezone.utc
        base = now.astimezone(tz)
        nxt = croniter(str(schedule["cron_expr"]), base).get_next(datetime)
        return nxt.astimezone(timezone.utc)
    raise ValueError(f"unknown schedule kind: {kind!r}")


def _ms(milliseconds: float):
    from datetime import timedelta

    return timedelta(milliseconds=milliseconds)


def validate(schedule: dict, kind: str) -> None:
    """Raise ValueError if the schedule dict is malformed for its kind (used at create time)."""
    if kind == "at":
        _parse_iso(str(schedule["at"]))
    elif kind == "every":
        if int(schedule["every_ms"]) <= 0:
            raise ValueError("every_ms must be positive")
    elif kind == "cron":
        from croniter import croniter

        if schedule.get("tz"):
            ZoneInfo(schedule["tz"])  # raises if unknown tz
        if not croniter.is_valid(str(schedule["cron_expr"])):
            raise ValueError(f"invalid cron expression: {schedule.get('cron_expr')!r}")
    else:
        raise ValueError(f"unknown schedule kind: {kind!r}")
