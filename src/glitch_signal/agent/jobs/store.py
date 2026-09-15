"""JOBS store — rows for the job spine, and nothing source-specific.

Every source writes the same `job_listing` row, which is what lets one dedup rule, one filter and
one approval UX serve all of them. Design: docs/plans/2026-09-15-job-application-agent.md § 8.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


# ON CONFLICT DO UPDATE, not DO NOTHING: re-seeing a posting is how we learn it is still live, and a
# later source often carries fields an earlier one lacked (Job Bank has no jd_text; the ATS does).
# COALESCE keeps whatever we already had rather than overwriting it with a NULL from a thinner source.
_UPSERT = text(
    "INSERT INTO job_listing (brand_id, source, canonical_url, company, title, location, posted_at, jd_text) "
    "VALUES (:b, :source, :url, :company, :title, :location, :posted_at, :jd) "
    "ON CONFLICT (brand_id, canonical_url) DO UPDATE SET "
    "  company  = COALESCE(EXCLUDED.company,  job_listing.company), "
    "  title    = COALESCE(EXCLUDED.title,    job_listing.title), "
    "  location = COALESCE(EXCLUDED.location, job_listing.location), "
    "  posted_at= COALESCE(EXCLUDED.posted_at,job_listing.posted_at), "
    "  jd_text  = COALESCE(EXCLUDED.jd_text,  job_listing.jd_text) "
    "RETURNING id, (xmax = 0) AS inserted"
)

_INSERT_EVAL = text(
    "INSERT INTO job_evaluation (listing_id, brand_id, score, score_parts, work_auth, report_md, model) "
    "VALUES (:lid, :b, :score, CAST(:parts AS jsonb), :wa, :report, :model) RETURNING id"
)

_UNSCORED = text(
    "SELECT l.id, l.source, l.canonical_url, l.company, l.title, l.location, l.jd_text "
    "FROM job_listing l "
    "LEFT JOIN job_evaluation e ON e.listing_id = l.id "
    "WHERE l.brand_id = :b AND e.id IS NULL "
    "ORDER BY l.first_seen_at DESC LIMIT :lim"
)

_COUNT_BY_SOURCE = text(
    "SELECT source, count(*) AS n FROM job_listing WHERE brand_id = :b GROUP BY source ORDER BY source"
)

_RECENT = text(
    "SELECT id, source, canonical_url, company, title, location, posted_at "
    "FROM job_listing WHERE brand_id = :b ORDER BY first_seen_at DESC LIMIT :lim"
)


def upsert_listing(brand_id: str, listing: dict, *, engine: Any = None) -> tuple[str, bool]:
    """Insert or refresh one listing. Returns (id, was_newly_inserted)."""
    eng = _engine_or(engine)
    with eng.begin() as conn:
        row = conn.execute(_UPSERT, {
            "b": brand_id,
            "source": listing["source"],
            "url": listing["canonical_url"],
            "company": listing.get("company"),
            "title": listing.get("title"),
            "location": listing.get("location"),
            "posted_at": listing.get("posted_at"),
            "jd": listing.get("jd_text"),
        }).first()
    return (str(row[0]), bool(row[1])) if row else ("", False)


def upsert_many(brand_id: str, listings: list[dict], *, engine: Any = None) -> dict:
    """Upsert a batch. Returns {'seen', 'inserted', 'updated'} — 'inserted' is what's actually new."""
    seen = inserted = 0
    for lst in listings:
        if not lst.get("canonical_url"):
            continue
        seen += 1
        _, was_new = upsert_listing(brand_id, lst, engine=engine)
        inserted += 1 if was_new else 0
    return {"seen": seen, "inserted": inserted, "updated": seen - inserted}


def counts_by_source(brand_id: str, *, engine: Any = None) -> dict[str, int]:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        return {r[0]: int(r[1]) for r in conn.execute(_COUNT_BY_SOURCE, {"b": brand_id})}


def recent(brand_id: str, limit: int = 25, *, engine: Any = None) -> list[dict]:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        rows = conn.execute(_RECENT, {"b": brand_id, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]


def record_evaluation(brand_id: str, listing_id: str, result: dict, *, engine: Any = None) -> str:
    """Persist one evaluation. Re-evaluation is allowed — the latest row by evaluated_at wins."""
    eng = _engine_or(engine)
    with eng.begin() as conn:
        row = conn.execute(_INSERT_EVAL, {
            "lid": listing_id, "b": brand_id,
            "score": result.get("score"),
            "parts": json.dumps(result.get("score_parts") or {}),
            "wa": result.get("work_auth"),
            "report": result.get("report_md"),
            "model": result.get("model"),
        }).first()
    return str(row[0]) if row else ""


def unscored(brand_id: str, limit: int = 10, *, engine: Any = None) -> list[dict]:
    """Listings with no evaluation yet, newest first."""
    eng = _engine_or(engine)
    with eng.begin() as conn:
        rows = conn.execute(_UNSCORED, {"b": brand_id, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]


# --- JOBS-5: applications + the approval lifecycle ------------------------------------

_UPSERT_APP = text(
    "INSERT INTO job_application (listing_id, brand_id, status, tailored_cv_path, answers) "
    "VALUES (:lid, :b, :status, :cv, CAST(:answers AS jsonb)) "
    "ON CONFLICT (listing_id) DO UPDATE SET "
    "  status = EXCLUDED.status, tailored_cv_path = COALESCE(EXCLUDED.tailored_cv_path, "
    "    job_application.tailored_cv_path), answers = EXCLUDED.answers "
    "RETURNING id"
)

_MARK_OFFERED = text(
    "UPDATE job_application SET status = 'awaiting_approval', discord_msg_id = :mid, "
    "  offered_at = now(), expires_at = now() + make_interval(hours => :ttl) WHERE id = :id"
)

_SET_APP_STATUS = text(
    "UPDATE job_application SET status = :status, "
    "  approved_at = CASE WHEN :approved THEN now() ELSE approved_at END, "
    "  approved_by = COALESCE(:by, approved_by), "
    "  failure_reason = COALESCE(:reason, failure_reason) WHERE id = :id"
)

# Expiry is NOT approval. A card nobody reacted to becomes `expired` and is never submitted.
_EXPIRE = text(
    "UPDATE job_application SET status = 'expired' "
    "WHERE brand_id = :b AND status = 'awaiting_approval' "
    "  AND expires_at IS NOT NULL AND expires_at < now() RETURNING id"
)

_BY_STATUS = text(
    "SELECT a.id, a.status, a.discord_msg_id, a.answers, a.tailored_cv_path, a.created_at, "
    "       l.canonical_url, l.company, l.title, l.location "
    "FROM job_application a JOIN job_listing l ON l.id = a.listing_id "
    "WHERE a.brand_id = :b AND a.status = ANY(:statuses) ORDER BY a.created_at"
)

# The 3/day cap counts SUBMITTED rows in the brand's own day, not per loop run.
_SUBMITTED_TODAY = text(
    "SELECT count(*) FROM job_application "
    "WHERE brand_id = :b AND submitted_at IS NOT NULL AND submitted_at >= date_trunc('day', now())"
)


def upsert_application(brand_id: str, listing_id: str, *, status: str = "drafted",
                       cv_path: str | None = None, answers: dict | None = None,
                       engine: Any = None) -> str:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        row = conn.execute(_UPSERT_APP, {"lid": listing_id, "b": brand_id, "status": status,
                                         "cv": cv_path, "answers": json.dumps(answers or {})}).first()
    return str(row[0]) if row else ""


def mark_offered(app_id: str, msg_id: str, ttl_hours: int = 48, *, engine: Any = None) -> None:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        conn.execute(_MARK_OFFERED, {"id": app_id, "mid": msg_id, "ttl": ttl_hours})


def set_application_status(app_id: str, status: str, *, approved: bool = False,
                           by: str | None = None, reason: str | None = None,
                           engine: Any = None) -> None:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        conn.execute(_SET_APP_STATUS, {"id": app_id, "status": status, "approved": approved,
                                       "by": by, "reason": reason})


def expire_stale(brand_id: str, *, engine: Any = None) -> list[str]:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        return [str(r[0]) for r in conn.execute(_EXPIRE, {"b": brand_id})]


def applications_by_status(brand_id: str, statuses: list[str], *, engine: Any = None) -> list[dict]:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        rows = conn.execute(_BY_STATUS, {"b": brand_id, "statuses": statuses}).mappings().all()
    return [dict(r) for r in rows]


def submitted_today(brand_id: str, *, engine: Any = None) -> int:
    eng = _engine_or(engine)
    with eng.begin() as conn:
        return int(conn.execute(_SUBMITTED_TODAY, {"b": brand_id}).scalar() or 0)
