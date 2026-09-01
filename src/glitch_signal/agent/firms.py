"""Prop-firm rule knowledge base — the only source of firm thresholds the agent may publish.

A firm rule is a precise, dated, attributable claim about a THIRD PARTY's product, published under
an affiliate relationship. If the model is left to supply the number it will invent one confidently,
and the conscience critic will not catch it: the critic's prohibitions cover OUR invented figures,
and a competitor's threshold reads to it as a legitimate fact. So rules come from this table or the
post does not state them.

The `publishable` flag matters more than the numbers. The upstream engine table this is seeded from
holds values that are CORRECT for backtesting and WRONG as public claims — synthetic gates, sentinel
zeros meaning "no such rule", and historical rules for a firm that is not currently selling. Each
would produce a fluent, plausible, false sentence.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)


async def publishable_rules(firm_id: str | None = None, *, engine: Any = None) -> list[dict]:
    """Rules cleared for public content. Never raises — no rules means the post says nothing."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            rows = (await conn.execute(
                text("SELECT firm_id, firm_name, rule_key, value_num, value_text, stage, source, "
                     "       as_of "
                     "FROM firm_rule WHERE publishable "
                     "  AND (cast(:f as text) IS NULL OR firm_id = cast(:f as text)) "
                     "ORDER BY firm_name, rule_key"),
                {"f": firm_id})).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.warning("firms.rules_lookup_failed", firm_id=firm_id, error=str(exc)[:200])
        return []


async def rules_for_names(names: list[str], *, engine: Any = None) -> dict[str, list[dict]]:
    """Map the firm NAMES the agent wrote in copy onto their publishable rules.

    Matching mirrors `assets.resolve_named`: the agent writes "FTMO" or "Apex", not a firm_id, so
    the lookup has to meet the copy where it is. A firm with no publishable rules simply yields
    nothing — the post can still name it, it just cannot quote a threshold for it.
    """
    have = await publishable_rules(engine=engine)
    out: dict[str, list[dict]] = {}
    for n in names:
        key = (n or "").strip().lower()
        if not key:
            continue
        for r in have:
            if key == r["firm_id"].lower() or key in r["firm_name"].lower():
                out.setdefault(r["firm_name"], []).append(r)
    return out


def rules_block(by_firm: dict[str, list[dict]]) -> str:
    """Render the rules as an authoritative prompt section, or '' when there are none.

    Returning '' rather than an empty header matters: an empty "VERIFIED FIRM RULES" block invites
    the model to fill the gap from its own priors, which is the exact failure this table exists to
    prevent.
    """
    if not by_firm:
        return ""
    lines = ["\n--- VERIFIED FIRM RULES (the ONLY firm thresholds you may state) ---"]
    for firm, rules in by_firm.items():
        for r in rules:
            lines.append(f"- {firm} · {r['stage']} stage · {r['rule_key']}: {r['value_text']} "
                         f"(as of {r['as_of']})")
    lines.append("State NO other firm threshold, percentage or figure. If a rule you want is not "
                 "listed here, write the post without it — do not infer, estimate or recall one.")
    return "\n".join(lines) + "\n"


# Names the agent is likely to write, mapped to what the table calls them. Kept explicit rather than
# fuzzy-matched: a loose match that pulled the wrong firm's thresholds into a post would be the
# exact failure this module exists to prevent.
_ALIASES: dict[str, str] = {
    "ftmo": "ftmo",
    "apex": "apex", "apex trader": "apex", "apex trader funding": "apex",
    "the5ers": "the5ers", "the 5ers": "the5ers", "5ers": "the5ers",
    "fundingpips": "fundingpips_zero", "funding pips": "fundingpips_zero",
    "getleveraged": "getleveraged_turbo", "get leveraged": "getleveraged_turbo",
    "fundednext": "fundednext", "funded next": "fundednext",
    "myforexfunds": "mff", "mff": "mff",
}


def mentioned(text_blob: str) -> list[str]:
    """Firm ids named anywhere in the copy. Longest alias wins so "apex trader funding" does not
    also match the shorter "apex" twice."""
    low = (text_blob or "").lower()
    hits: list[str] = []
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in low and _ALIASES[alias] not in hits:
            hits.append(_ALIASES[alias])
    return hits
