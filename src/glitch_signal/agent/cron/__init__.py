"""AGENT-CRON — the agent's self-cron: it schedules its own future work.

A durable scheduler where the operator (via /internal/cron/*) and the agent (via the self-scoped
`schedule` loop tool) queue future work — an agent turn on a goal, or an allowlisted capability
(curate, reconcile, …). The per-worker scheduler tick claims due jobs exactly-once (SKIP LOCKED)
and dispatches them. NOT the social-post scheduler.
"""
from glitch_signal.agent.cron.service import sweep
from glitch_signal.agent.cron.tool import schedule_tool

__all__ = ["sweep", "schedule_tool"]
