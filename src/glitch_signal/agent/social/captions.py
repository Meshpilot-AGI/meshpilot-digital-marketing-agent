from __future__ import annotations

import json

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_MAX = 2200

_SYS = ("Write a single social caption for brand '{brand}' in its established voice. No hashspam, "
        "no forbidden hype words, no invented claims/metrics. Return ONLY the caption text."
        "{positioning}")

_ASK = ("Angle: {angle}\nHook: {hook}\nKey points: {points}\nMedium: {medium}\n"
        "Write the caption for a {medium} post.")


async def _polish(brand_id: str, text: str) -> str:
    """Run drafted copy through the `polish_copy` tool (mandatory content-policy pass).

    `_t_polish_copy` in `agent/loop/tools.py` is a plain, network-free async function
    (`args: dict, brand_id: str) -> str`, JSON-encoding `{"clean", "violations"}`) — it is
    cleanly importable without the tool-loop machinery, so every caption is run through it
    before the length trim.
    """
    from glitch_signal.agent.loop.tools import _t_polish_copy
    raw = await _t_polish_copy({"text": text}, brand_id)
    try:
        return json.loads(raw).get("clean", text)
    except (json.JSONDecodeError, AttributeError):
        log.warning("social.captions.polish_parse_failed", brand_id=brand_id)
        return text


async def _one(brand_id: str, idea: Idea, medium: str, complete, positioning: str = "") -> str:
    raw = await complete(
        _ASK.format(angle=idea.angle, hook=idea.hook,
                    points="; ".join(idea.key_points), medium=medium),
        system=_SYS.format(brand=brand_id, positioning=positioning), tier="complex", timeout_s=40)
    text = (raw or idea.hook).strip()
    text = await _polish(brand_id, text)
    return text[:_MAX]


async def write_captions(brand_id: str, idea: Idea, *, complete=None, positioning=None,
                         engine=None) -> dict[str, str]:
    """Draft the image + video captions. The positioning doc carries VOICE and the never-say list —
    the facts say what is true, this says how this brand is allowed to sound."""
    from glitch_signal.agent import positioning as _positioning
    from glitch_signal.agent.loop import llm as agent_llm
    complete = complete or agent_llm.complete
    positioning = positioning or _positioning.get
    pos_txt = _positioning.section(await positioning(brand_id, engine=engine))
    return {"image": await _one(brand_id, idea, "image", complete, pos_txt),
            "video": await _one(brand_id, idea, "video", complete, pos_txt)}
