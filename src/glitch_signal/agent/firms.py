"""Prop-firm rule knowledge base — the only source of firm thresholds the agent may publish.

A firm rule is a precise, dated claim about a third party's product. Left unconstrained, the model
invents plausible numbers the conscience critic won't catch — its prohibitions cover our own
invented figures, not a competitor's threshold stated as fact. So rules come from this table or not
at all.

The `publishable` flag matters more than the numbers: the upstream engine table this is seeded from
also holds backtesting values that are wrong as public claims (synthetic gates, sentinel zeros for
"no such rule", rules for firms no longer selling) — each would read as a fluent, false sentence.
"""
from __future__ import annotations

import re
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
    """Map the firm names the agent wrote in copy (e.g. "FTMO", not a firm_id) onto their
    publishable rules — mirrors `assets.resolve_named`. No rules just means no threshold quoted."""
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


_DEGENERATE = re.compile(r"\bevery 0\b|\b0 days\b|\b0% ", re.I)


def _degenerate(value_text: str | None) -> bool:
    """True when a figure has been formatted into a phrase it cannot support ('every 0 days')."""
    return bool(_DEGENERATE.search(str(value_text or "")))


def rules_block(by_firm: dict[str, list[dict]]) -> str:
    """Verified firm rules as a fact block for a model prompt.

    ⚠️ Rules whose TEXT renders as a degenerate quantity are omitted. A published post said "The5ers
    High Stakes lists payout cadence as every 0 days" (2026-09-02) — faithful to our row, which said
    exactly that. Grounding guarantees fidelity to our data, not the correctness of it.

    The filter is on the text, not on `value_num`, and that distinction was learned the hard way: the
    first version dropped any non-positive `value_num`, which would have suppressed this fact
    entirely. `payoutCadenceDays: 0` is a deliberate SENTINEL in the app's engine table meaning
    *on-demand payouts* — a real differentiator worth stating, and the widgets read that zero. The
    row was wrong in how it was worded, not in what it held. So: fix the wording, keep the fact, and
    screen only for a number that has been formatted into a phrase it cannot support.
    """
    by_firm = {f: [r for r in rules if not _degenerate(r.get("value_text"))]
               for f, rules in (by_firm or {}).items()}
    by_firm = {f: r for f, r in by_firm.items() if r}
    """Render the rules as an authoritative prompt section, or '' when there are none — an empty
    header would invite the model to fill the gap from its own priors."""
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


# Names the agent is likely to write, mapped to what the table calls them. Kept explicit, not
# fuzzy-matched — a loose match pulling the wrong firm's thresholds into a post is the failure
# this module exists to prevent.
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
