"""Critical review findings — the ones that would misbehave in public."""
import os
import subprocess
import sys

import pytest

from glitch_signal.agent.social import technique
from glitch_signal.platforms import insights


# ── #205: Meta tokens leaked through error messages (SECURITY) ──────────────────────────────────
def test_token_is_never_a_query_parameter():
    """httpx puts the full request URL into HTTPStatusError.__str__, and these calls log on failure
    by design — so a token in the query string lands in every logged error."""
    src = __import__("pathlib").Path(insights.__file__).read_text()
    assert '"access_token": token' not in src
    assert '"access_token": system_token' not in src
    assert "_auth(" in src                     # carried in the Authorization header instead


def test_error_text_redacts_any_surviving_credential():
    """Defence in depth: a library we do not control may still echo a URL we did not construct."""
    leaked = insights._safe(RuntimeError(
        "400 for https://graph.facebook.com/v26.0/x/insights?access_token=EAAWsecret123&metric=y"))
    assert "EAAWsecret123" not in leaked and "<redacted>" in leaked


def test_redaction_also_catches_bearer_form():
    assert "sk-abc123" not in insights._safe(RuntimeError("Authorization: Bearer sk-abc123"))


# ── #210: the "deterministic" backdrop seed was not deterministic ───────────────────────────────
def test_str_hash_really_is_unstable_across_processes():
    """Establishes the premise rather than asserting it: Python randomises str.__hash__ per process,
    so the original `abs(hash(headline))` gave a different backdrop on every restart while the
    docstring claimed reproducibility.

    Both subprocesses must NOT inherit a fixed `PYTHONHASHSEED` from the test runner's own
    environment — if the runner (CI or a developer shell) pins that variable, both children would
    reuse the identical seed and produce identical hashes, failing this premise test despite
    correct production behaviour. The env passed to each child is scrubbed of it so each interpreter
    starts up with its own randomised seed, same as production."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONHASHSEED"}
    code = 'print(abs(hash("a-headline")))'
    a = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env).stdout
    b = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env).stdout
    assert a != b


def test_backdrop_seed_is_stable_across_processes():
    code = ('import hashlib;'
            'print(int(hashlib.sha256(b"a-headline").hexdigest()[:8], 16))')
    a = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    b = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    assert a == b and a.strip()


# ── #209: raw copy tokens pulled unrelated firms' logos ─────────────────────────────────────────
def test_logos_resolve_from_curated_aliases_not_raw_copy_tokens():
    """Splitting the copy on whitespace fed every ordinary word to a substring matcher — "next"
    matches "FundedNext" — so an unrelated firm's mark could land on a post that never named it.
    Publishing a competitor's logo on the wrong post is a partner problem, not a cosmetic one."""
    from glitch_signal.agent import firms
    from glitch_signal.agent.social import campaign

    src = __import__("pathlib").Path(campaign.__file__).read_text()
    assert "blob.split()" not in src
    assert "_firms.mentioned(blob)" in src
    # the curated matcher does not fire on ordinary prose
    assert firms.mentioned("what comes next for your account") == []
    assert firms.mentioned("FundedNext raised its target") == ["fundednext"]


# ── #207: the matrix assignment was a suggestion the model could decline ────────────────────────
def test_idea_is_frozen_so_the_override_must_use_replace():
    """Guards the fix itself: an in-place assignment would raise at runtime, inside a paid run."""
    import dataclasses

    from glitch_signal.agent.social.spec import Idea

    idea = Idea(angle="a", hook="h", key_points=[], dedup_key="k", asset_kind="statement")
    with pytest.raises(dataclasses.FrozenInstanceError):
        idea.asset_kind = "comparison"
    assert dataclasses.replace(idea, asset_kind="comparison").asset_kind == "comparison"


def test_campaign_enforces_the_assigned_cell():
    from glitch_signal.agent.social import campaign

    src = __import__("pathlib").Path(campaign.__file__).read_text()
    assert "dataclasses.replace(idea, asset_kind=cell.asset_kind)" in src
    assert "model_preferred" in src            # the override stays visible, not silent


# ── backdrops must read as TRADING, or they build no identity ───────────────────────────────────
def test_every_backdrop_subject_is_a_trading_desk():
    """A generic workstation is interchangeable with any software brand — it builds no identity."""
    assert all("trading" in s for s in technique.BACKDROP_SUBJECTS)


def test_backdrop_subjects_keep_the_interface_unreadable():
    """A legible figure on a rendered terminal would be a number we invented — the same prohibition
    the copy follows."""
    joined = " ".join(technique.BACKDROP_SUBJECTS).lower()
    assert "blur" in joined or "out of focus" in joined or "unreadable" in joined
    assert "no legible text or numbers" in joined
