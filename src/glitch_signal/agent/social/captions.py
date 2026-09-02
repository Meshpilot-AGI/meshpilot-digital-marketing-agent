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


async def _one(brand_id: str, idea: Idea, medium: str, complete, positioning: str = "",
               platform_ctx: str = "") -> str:
    raw = await complete(
        _ASK.format(angle=idea.angle, hook=idea.hook,
                    points="; ".join(idea.key_points), medium=medium) + platform_ctx,
        system=_SYS.format(brand=brand_id, positioning=positioning), tier="complex", timeout_s=40)
    text = (raw or idea.hook).strip()
    text = await _polish(brand_id, text)
    return text[:_MAX]


async def write_captions(brand_id: str, idea: Idea, *, platforms: dict[str, str] | None = None,
                         complete=None, positioning=None, engine=None) -> dict[str, str]:
    """Draft one caption PER PLATFORM.

    Previously this wrote one caption per MEDIUM and every platform of that medium reused it — the
    identical text went to X, LinkedIn and Facebook. Those are different rooms with different
    lengths, registers and norms, and a caption tuned for none of them is tuned for all of them
    badly. On a brand whose whole positioning is "sounds like someone who has been there", generic
    copy is the specific thing that breaks it.

    `platforms` maps platform -> medium. Falls back to the old per-medium behaviour when omitted, so
    an unprofiled brand still posts. The returned dict is keyed by BOTH platform and medium, so
    callers can look up either.
    """
    from glitch_signal.agent import positioning as _positioning
    from glitch_signal.agent.social import platforms_kb as _kb
    from glitch_signal.agent.loop import llm as agent_llm
    complete = complete or agent_llm.complete
    positioning = positioning or _positioning.get
    pos_txt = _positioning.section(await positioning(brand_id, engine=engine))

    if not platforms:
        return {"image": await _one(brand_id, idea, "image", complete, pos_txt),
                "video": await _one(brand_id, idea, "video", complete, pos_txt)}

    from glitch_signal.agent import firms as _firms

    named = _firms.mentioned(f"{idea.angle} {idea.hook} {' '.join(idea.key_points or [])}")
    out: dict[str, str] = {}
    for platform, medium in platforms.items():
        prof = await _kb.profile(brand_id, platform, engine=engine)
        handles = await _kb.handles_for(brand_id, named, platform, engine=engine)
        ctx = _kb.section(prof) + _kb.mention_line(handles, platform)
        out[platform] = await _one(brand_id, idea, medium, complete, pos_txt, ctx)
    # keep medium keys populated so any caller still asking for them keeps working
    for medium in ("image", "video"):
        if medium not in out:
            first = next((p for p, m in platforms.items() if m == medium), None)
            if first:
                out[medium] = out[first]
    return out
