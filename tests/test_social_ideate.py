import json
from glitch_signal.agent.social import ideate


async def _recall_stub(brand_id, query, *, k=8, kinds=None, verified_only=False, engine=None):
    return []


async def test_propose_idea_parses_llm_json():
    async def _complete(prompt, *, system=None, model=None, tier=None, timeout_s=90):
        return json.dumps({"angle": "risk mgmt", "hook": "Blow-ups are optional",
                           "key_points": ["stop-loss"], "dedup_key": "risk-mgmt-2026"})
    idea = await ideate.propose_idea("ge", complete=_complete, recall=_recall_stub, recent_keys=set())
    assert idea is not None and idea.dedup_key == "risk-mgmt-2026" and idea.angle == "risk mgmt"


async def test_propose_idea_dedups_recent():
    async def _complete(prompt, *, system=None, model=None, tier=None, timeout_s=90):
        return json.dumps({"angle": "a", "hook": "h", "key_points": [], "dedup_key": "seen"})
    idea = await ideate.propose_idea("ge", complete=_complete, recall=_recall_stub,
                                     recent_keys={"seen"})
    assert idea is None    # collides → skip
