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


_UPSERT_APP = text(
    "INSERT INTO job_application (listing_id, brand_id, status, tailored_cv_path, tailored_cv_md, answers) "
    "VALUES (:lid, :b, :status, :cv, :cv_md, CAST(:answers AS jsonb)) "
    "ON CONFLICT (listing_id) DO UPDATE SET "
    "  status = EXCLUDED.status, tailored_cv_path = COALESCE(EXCLUDED.tailored_cv_path, "
    "    job_application.tailored_cv_path), "
    # COALESCE, not overwrite: a later call that does not carry the markdown (a status refresh, a
    # render recording its path) must never erase the document the operator approved.
    "  tailored_cv_md = COALESCE(EXCLUDED.tailored_cv_md, job_application.tailored_cv_md), "
    "  answers = EXCLUDED.answers "
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
    "SELECT a.id, a.listing_id, a.status, a.discord_msg_id, a.answers, a.tailored_cv_path, "
    # The approved markdown travels with the row: the submitter re-renders THAT document rather than
    # tailoring a fresh one, so what is sent is what was approved.
    "       a.tailored_cv_md, "
    "       a.submitted_at, a.created_at, "
    "       l.canonical_url, l.company, l.title, l.location "
    "FROM job_application a JOIN job_listing l ON l.id = a.listing_id "
    "WHERE a.brand_id = :b AND a.status = ANY(:statuses) ORDER BY a.created_at"
)

# The 3/day cap counts SUBMITTED rows in the brand's own day, not per loop run.
_SUBMITTED_TODAY = text(
    "SELECT count(*) FROM job_application "
    "WHERE brand_id = :b AND submitted_at IS NOT NULL AND submitted_at >= date_trunc('day', now())"
)

_ANSWER_BANK = text("SELECT question, answer FROM job_answer_bank WHERE brand_id = :b")

_MARK_SUBMITTED = text(
    "UPDATE job_application SET status = 'submitted', submitted_at = now(), "
    "  evidence = CAST(:evidence AS jsonb) WHERE id = :id AND submitted_at IS NULL RETURNING id"
)


def _as_datetime(value: Any) -> Any:
    """Coerce a source's `posted_at` to a datetime, or None.

    ⚠️ This is why `job_listing` was EMPTY (found on the first live run, 2026-09-15). Every source
    carries `posted_at` as an ISO STRING — that is what the feeds and ATS APIs return — and asyncpg
    binds parameters by type rather than letting Postgres cast them, so the insert died with
    `invalid input for query argument $7`. One `_gather` catch upstream turned that into a logged
    warning, so discovery reported success and stored NOTHING, every run, since JOBS-2.

    Coercing here rather than in each source is deliberate: there are five sources and one store, and
    the next source added would have reintroduced the bug. An unparseable value becomes None — a
    listing with no date is worth keeping; losing the listing over its date is not.
    """
    from datetime import datetime

    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


async def upsert_listing(brand_id: str, listing: dict, *, engine: Any = None) -> tuple[str, bool]:
    """Insert or refresh one listing. Returns (id, was_newly_inserted)."""
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_UPSERT, {
            "b": brand_id,
            "source": listing["source"],
            "url": listing["canonical_url"],
            "company": listing.get("company"),
            "title": listing.get("title"),
            "location": listing.get("location"),
            "posted_at": _as_datetime(listing.get("posted_at")),
            "jd": listing.get("jd_text"),
        })
        row = res.first()
    return (str(row[0]), bool(row[1])) if row else ("", False)


async def upsert_many(brand_id: str, listings: list[dict], *, engine: Any = None) -> dict:
    """Upsert a batch. Returns {'seen', 'inserted', 'updated'} — 'inserted' is what's actually new."""
    seen = inserted = 0
    for lst in listings:
        if not lst.get("canonical_url"):
            continue
        seen += 1
        _, was_new = await upsert_listing(brand_id, lst, engine=engine)
        inserted += 1 if was_new else 0
    return {"seen": seen, "inserted": inserted, "updated": seen - inserted}


async def counts_by_source(brand_id: str, *, engine: Any = None) -> dict[str, int]:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_COUNT_BY_SOURCE, {"b": brand_id})
        return {r[0]: int(r[1]) for r in res}


async def recent(brand_id: str, limit: int = 25, *, engine: Any = None) -> list[dict]:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_RECENT, {"b": brand_id, "lim": limit})
        return [dict(r) for r in res.mappings().all()]


async def record_evaluation(brand_id: str, listing_id: str, result: dict, *,
                            engine: Any = None) -> str:
    """Persist one evaluation. Re-evaluation is allowed — the latest row by evaluated_at wins."""
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_INSERT_EVAL, {
            "lid": listing_id, "b": brand_id,
            "score": result.get("score"),
            "parts": json.dumps(result.get("score_parts") or {}),
            "wa": result.get("work_auth"),
            "report": result.get("report_md"),
            "model": result.get("model"),
        })
        row = res.first()
    return str(row[0]) if row else ""


async def unscored(brand_id: str, limit: int = 10, *, engine: Any = None) -> list[dict]:
    """Listings with no evaluation yet, newest first."""
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_UNSCORED, {"b": brand_id, "lim": limit})
        return [dict(r) for r in res.mappings().all()]


_OFFER_CANDIDATES = text(
    # Scored listings with NO application row yet, best score first. The LEFT JOIN on job_application
    # is the idempotency guard that keeps a re-run from offering the same role twice; the LATERAL
    # takes the most RECENT evaluation, because a re-score must not be shadowed by its first verdict.
    "SELECT l.id AS listing_id, l.canonical_url, l.company, l.title, l.location, l.jd_text, "
    "       e.score, e.score_parts, e.work_auth "
    "FROM job_listing l "
    "JOIN LATERAL ("
    "  SELECT score, score_parts, work_auth FROM job_evaluation "
    "  WHERE listing_id = l.id ORDER BY evaluated_at DESC LIMIT 1) e ON true "
    # ⚠️ `a.id IS NULL` alone BURIED a role permanently, and it buried the best one. `hunt.run`
    # writes the application row BEFORE posting the card (that ordering is the double-offer guard),
    # so when the Discord post failed — a missing token on the first cloud run — the listing kept a
    # `drafted` row with no `discord_msg_id` and this query excluded it from then on. The failure was
    # reported once, in that run's `errors`; every run after it was silent. A 4.5 role, the only one
    # over the floor, would have sat unseen forever.
    #
    # A draft that was never offered is a RETRY candidate, not a finished one. Anything further along
    # (offered, approved, skipped, submitted) is correctly excluded.
    "LEFT JOIN job_application a ON a.listing_id = l.id "
    "WHERE l.brand_id = :b AND e.score IS NOT NULL "
    "  AND (a.id IS NULL OR (a.status = 'drafted' AND a.discord_msg_id IS NULL)) "
    "ORDER BY e.score DESC NULLS LAST, l.first_seen_at DESC LIMIT :lim")


async def offer_candidates(brand_id: str, limit: int = 10, *, engine: Any = None) -> list[dict]:
    """Scored listings with no application row yet, best score first.

    The floor is NOT applied here — `score.meets_floor` owns that decision, and applying it in SQL
    too would put the operator's threshold in two places that can disagree.
    """
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_OFFER_CANDIDATES, {"b": brand_id, "lim": limit})
        return [dict(r) for r in res.mappings().all()]


async def upsert_application(brand_id: str, listing_id: str, *, status: str = "drafted",
                             cv_path: str | None = None, answers: dict | None = None,
                             cv_md: str | None = None, engine: Any = None) -> str:
    """Create or refresh the application row.

    `cv_md` is the VERIFIED tailored markdown the operator will see on the card — stored so the
    approval binds to the artifact it approved. Without it a later submission would re-tailor and
    send a different document than the one that was shown.
    """
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_UPSERT_APP, {
            "lid": listing_id, "b": brand_id, "status": status,
            "cv": cv_path, "cv_md": cv_md, "answers": json.dumps(answers or {})})
        row = res.first()
    return str(row[0]) if row else ""


async def mark_offered(app_id: str, msg_id: str, ttl_hours: int = 48, *,
                       engine: Any = None) -> None:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        await conn.execute(_MARK_OFFERED, {"id": app_id, "mid": msg_id, "ttl": ttl_hours})


async def set_application_status(app_id: str, status: str, *, approved: bool = False,
                                 by: str | None = None, reason: str | None = None,
                                 engine: Any = None) -> None:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        await conn.execute(_SET_APP_STATUS, {"id": app_id, "status": status, "approved": approved,
                                             "by": by, "reason": reason})


async def expire_stale(brand_id: str, *, engine: Any = None) -> list[str]:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_EXPIRE, {"b": brand_id})
        return [str(r[0]) for r in res]


async def applications_by_status(brand_id: str, statuses: list[str], *,
                                 engine: Any = None) -> list[dict]:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_BY_STATUS, {"b": brand_id, "statuses": statuses})
        return [dict(r) for r in res.mappings().all()]


async def submitted_today(brand_id: str, *, engine: Any = None) -> int:
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_SUBMITTED_TODAY, {"b": brand_id})
        return int(res.scalar() or 0)


async def answer_bank(brand_id: str, *, engine: Any = None) -> dict[str, str]:
    """The operator's answer bank, keyed by NORMALIZED question. Exact match only (decision 4)."""
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_ANSWER_BANK, {"b": brand_id})
        return {r[0]: r[1] for r in res}


async def mark_submitted(app_id: str, evidence: dict, *, engine: Any = None) -> bool:
    """Record a submission. Returns False if the row was ALREADY submitted — the guard against a
    double submission racing through two workers. `submitted_at IS NULL` makes it atomic."""
    eng = _engine_or(engine)
    async with eng.begin() as conn:
        res = await conn.execute(_MARK_SUBMITTED,
                                 {"id": app_id, "evidence": json.dumps(evidence or {})})
        row = res.first()
    return bool(row)
