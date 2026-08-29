"""The job currently executing in this task — so an agentTurn's `next_check` re-paces its own job.

Set by the dispatcher inside each job's task (contextvars are per-task); read by the `schedule`
tool's `next_check` action.
"""
from __future__ import annotations

import contextvars

current_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("cron_job_id", default=None)
current_job_pacing: contextvars.ContextVar[dict | None] = contextvars.ContextVar("cron_job_pacing", default=None)
