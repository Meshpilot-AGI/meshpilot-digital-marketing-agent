from datetime import UTC


def test_posted_at_strings_are_coerced_because_asyncpg_will_not_cast_them():
    """⚠️ The reason `job_listing` sat EMPTY from JOBS-2 until 2026-09-15. Sources return `posted_at`
    as an ISO string; asyncpg binds by type instead of letting Postgres cast, so every insert died
    with `invalid input for query argument $7` — and a `_gather` catch upstream logged it as a
    warning, so discovery reported success and stored nothing, every run.

    The unit tests never saw it because they all mock the store. Only a live run could.
    """
    from datetime import datetime

    from glitch_signal.agent.jobs.store import _as_datetime

    assert _as_datetime("2026-09-14T15:20:17.891+00:00") == datetime(
        2026, 9, 14, 15, 20, 17, 891000, tzinfo=UTC)
    assert _as_datetime("2026-09-14T15:20:17Z").tzinfo is not None   # the Z form feeds fromisoformat
    assert _as_datetime(None) is None
    # A listing with an unreadable date is still worth keeping; losing it over the date is not.
    assert _as_datetime("last tuesday") is None
    now = datetime.now(UTC)
    assert _as_datetime(now) is now


def test_offer_candidates_retries_a_draft_whose_card_never_posted():
    """⚠️ Observed live 2026-09-15. `hunt.run` writes the application row BEFORE posting the card —
    that ordering is the double-offer guard — so when the Discord post failed, the listing kept a
    `drafted` row with no `discord_msg_id` and the old `a.id IS NULL` filter excluded it from every
    later run. The failure was reported once, in that run's `errors`, and was silent afterwards. The
    role it buried was 4.5: the only one over the floor.

    A draft that was never offered is a retry candidate. Anything further along is not.
    """
    from glitch_signal.agent.jobs.store import _OFFER_CANDIDATES

    sql = " ".join(str(_OFFER_CANDIDATES).split())
    assert "a.status = 'drafted' AND a.discord_msg_id IS NULL" in sql
    assert "a.id IS NULL OR" in sql, "a listing with no application at all is still the main case"
