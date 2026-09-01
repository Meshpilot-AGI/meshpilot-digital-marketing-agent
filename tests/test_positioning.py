"""Brand positioning reaches the ideator, the caption writer AND the critic.

Regression origin: 0 of 33 GE facts passed the verified gate, so `propose_idea` received
"(none)" as brand facts and invented prop-firm-payout positioning for a brand that is not a prop
firm — and the critic, given no ground truth either, could not catch it.
"""
import pytest

from glitch_signal.agent import positioning
from glitch_signal.agent.loop import conscience
from glitch_signal.agent.social import captions, ideate
from glitch_signal.agent.social.spec import Idea
from tests.test_agent_memory import FakeEngine, _Result


def test_section_is_empty_when_there_is_no_doc():
    """An empty '--- BRAND POSITIONING ---' header reads to the model as 'this brand has no
    positioning', which is worse than saying nothing at all."""
    assert positioning.section("") == ""
    assert positioning.section("   ") == ""
    assert "BRAND POSITIONING" in positioning.section("we are not a prop firm")


async def test_get_returns_empty_and_does_not_raise_on_db_failure():
    """Grounding is additive — a positioning read failure must never abort a paid campaign."""
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")

    assert await positioning.get("ge", engine=_Boom()) == ""


async def test_get_reads_the_brand_scoped_row():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("we are not a prop firm",)]))
    assert await positioning.get("ge", engine=eng) == "we are not a prop firm"
    _sql, params = eng.calls[0]
    assert params["brand"] == "ge"


async def test_ideator_prompt_carries_the_positioning():
    """The ideator invented positioning from the brand NAME when grounding was empty. The doc has
    to be in the prompt, and it has to outrank the model's own priors."""
    seen = {}

    async def complete(prompt, **k):
        seen["prompt"] = prompt
        return '{"angle":"a","hook":"h","key_points":["p"],"dedup_key":"k1"}'

    async def recall(brand, q, **k):
        return []

    async def pos(brand_id, engine=None):
        return "We are NOT a prop firm. Never produce payout content."

    idea = await ideate.propose_idea("ge", complete=complete, recall=recall, positioning=pos)
    assert idea is not None
    assert "We are NOT a prop firm" in seen["prompt"]
    assert "the positioning wins" in seen["prompt"]      # it outranks the model's priors


async def test_caption_writer_gets_positioning_as_system_guidance():
    """Voice and the never-say list live in the positioning doc, so the caption writer needs it —
    the facts alone cannot say how a brand is allowed to SOUND."""
    seen = {}

    async def complete(prompt, *, system=None, **k):
        seen["system"] = system
        return "a caption"

    async def pos(brand_id, engine=None):
        return "Peer with warmth. Never use rocket emoji."

    monkey = await captions.write_captions(
        "ge", Idea("a", "h", ["p"], "k"), complete=complete, positioning=pos)
    assert monkey["image"]
    assert "Never use rocket emoji" in seen["system"]


async def test_critic_receives_positioning_labelled_separately_from_facts(monkeypatch):
    """Facts are checkable claims; positioning is judgement. Mislabelling judgement as ground truth
    would let a positioning statement launder itself into an authorized claim."""
    seen = {}

    async def complete(prompt, *, system=None, **k):
        seen["prompt"] = prompt
        return '{"verdict":"escalate","notes":"off-brand"}'

    monkeypatch.setattr(conscience, "constitution", lambda: "BE HONEST")
    out = await conscience.review("goal", "we pay out $100k", facts="GE is a trading platform.",
                                  positioning="We are NOT a prop firm.", complete=complete)
    assert out["verdict"] == "escalate"
    p = seen["prompt"]
    assert "VERIFIED BRAND FACTS" in p and "BRAND POSITIONING" in p
    # The two blocks must be distinct — positioning is explicitly NOT claim authorization.
    assert "NOT claim authorization" in p
    assert p.index("VERIFIED BRAND FACTS") < p.index("BRAND POSITIONING")


async def test_critic_omits_the_positioning_block_when_there_is_none(monkeypatch):
    seen = {}

    async def complete(prompt, *, system=None, **k):
        seen["prompt"] = prompt
        return '{"verdict":"pass","notes":"ok"}'

    monkeypatch.setattr(conscience, "constitution", lambda: "BE HONEST")
    await conscience.review("goal", "output", facts="", positioning="", complete=complete)
    assert "BRAND POSITIONING" not in seen["prompt"]


# ── recall lexical degradation (regression) ──────────────────────────────────────────────────
from glitch_signal.agent.memory import store as mem_store  # noqa: E402


def test_or_tsquery_joins_terms_with_or_not_and():
    """plainto_tsquery ANDs every term, so 'brand identity product pricing' required a row to
    contain ALL of them — almost nothing does. As a hard `@@` filter that returned zero candidates."""
    assert mem_store._or_tsquery("brand identity product pricing") == "brand | identity | product | pricing"


def test_or_tsquery_strips_tsquery_operators():
    """to_tsquery parses operator syntax, so raw text with & ! : or quotes would raise."""
    out = mem_store._or_tsquery("brand & identity ! 'pricing':A")
    assert "&" not in out and "!" not in out and ":" not in out and "'" not in out
    assert out == "brand | identity | pricing"


def test_or_tsquery_empty_input_yields_empty_string():
    """An empty tsquery is a SYNTAX ERROR in Postgres, not an empty match — callers must drop the
    lexical filter entirely rather than pass ''."""
    assert mem_store._or_tsquery("") == ""
    assert mem_store._or_tsquery("!!! & :") == ""


async def test_recall_without_embeddings_still_returns_candidates(monkeypatch):
    """The documented contract is 'degrade to lexical, never block'. When the embedding fails,
    sem_cand is skipped and lex_cand is the ONLY candidate source — an AND-semantics hard filter
    there made recall return nothing at all, which is how the agent ended up with empty grounding."""
    from tests.test_agent_memory import FakeEngine, _Result, _Row

    async def _no_embed(*a, **k):
        return None

    monkeypatch.setattr(mem_store, "_embed_or_none", _no_embed)
    eng = FakeEngine()
    eng.queue(_Result(rows=[_Row({"id": "m1", "brand_id": "ge", "kind": "fact", "key": None,
                                  "content": "GE is not a prop firm", "metadata": {},
                                  "importance": 1, "source": "operator_verified",
                                  "created_at": None, "last_used_at": None,
                                  "semantic": 0, "lexical": 0.1, "score": 0.1})]))
    eng.queue(_Result(rowcount=1))
    mems = await mem_store.recall("ge", "brand identity product pricing", k=5, engine=eng)
    assert len(mems) == 1
    sql, params = eng.calls[0]
    assert "to_tsquery" in sql and "plainto_tsquery" not in sql
    assert params["qts"] == "brand | identity | product | pricing"


async def test_recall_with_untokenizable_query_drops_the_lexical_filter(monkeypatch):
    """No usable tokens must fall back to recency, not emit to_tsquery('') and raise."""
    from tests.test_agent_memory import FakeEngine, _Result

    async def _no_embed(*a, **k):
        return None

    monkeypatch.setattr(mem_store, "_embed_or_none", _no_embed)
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await mem_store.recall("ge", "&&& !!!", k=5, engine=eng)
    sql, params = eng.calls[0]
    assert params["qts"] == ""
    assert "@@ to_tsquery" not in sql            # filter dropped entirely
    assert "importance DESC, created_at DESC" in sql   # recency fallback
