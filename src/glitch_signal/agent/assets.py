"""Brand asset library — the real image files the creative pipeline composites in.

An image model asked for a third-party mark (FTMO, MT5) produces a mangled, trademark-misrepresenting
approximation — so logos are never generated, only stored files placed by code.

Assets are scoped to an OWNER brand (the tenant), while `slug`/`name` identify the DEPICTED brand,
usually a third party we integrate with.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

KINDS = ("logo", "product_shot", "icon", "backdrop")


async def register(owner_brand: str, *, kind: str, slug: str, name: str, url: str,
                   width: int | None = None, height: int | None = None,
                   accent: str | None = None, usage_note: str | None = None,
                   engine: Any = None) -> None:
    """Upsert one asset. Re-registering the same (owner, kind, slug) replaces the file."""
    if kind not in KINDS:
        raise ValueError(f"unknown asset kind {kind!r}; allowed: {KINDS}")
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("INSERT INTO brand_asset (owner_brand, kind, slug, name, url, width, height, "
                 "accent, usage_note) VALUES (:o, :k, :s, :n, :u, :w, :h, :a, :note) "
                 "ON CONFLICT (owner_brand, kind, slug) DO UPDATE SET "
                 "name = excluded.name, url = excluded.url, width = excluded.width, "
                 "height = excluded.height, accent = excluded.accent, "
                 "usage_note = excluded.usage_note"),
            {"o": owner_brand, "k": kind, "s": slug, "n": name, "u": url,
             "w": width, "h": height, "a": accent, "note": usage_note})


async def find(owner_brand: str, *, kind: str | None = None, slug: str | None = None,
               engine: Any = None) -> list[dict]:
    """Look assets up. Never raises — a missing library degrades to no imagery, not a failed run."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            rows = (await conn.execute(
                text("SELECT slug, name, kind, url, width, height, accent, usage_note, handles "
                     "FROM brand_asset WHERE owner_brand = :o "
                     "  AND (cast(:k as text) IS NULL OR kind = cast(:k as text)) "
                     "  AND (cast(:s as text) IS NULL OR slug = cast(:s as text)) "
                     "ORDER BY name"),
                {"o": owner_brand, "k": kind, "s": slug})).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            h = d.get("handles")
            if isinstance(h, str):          # asyncpg may hand jsonb back as text
                import json
                try:
                    h = json.loads(h)
                except Exception:  # noqa: BLE001
                    h = {}
            d["handles"] = h if isinstance(h, dict) else {}
            out.append(d)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("brand.assets_lookup_failed", owner_brand=owner_brand, error=str(exc)[:200])
        return []


async def resolve_named(owner_brand: str, names: list[str], *, kind: str = "logo",
                        engine: Any = None) -> list[dict]:
    """Match free-text names the agent used ("FTMO", "Apex") onto real assets. Case-insensitive on
    both name and slug; unmatched names are dropped so the post still renders, just without a mark.
    """
    have = await find(owner_brand, kind=kind, engine=engine)
    out: list[dict] = []
    for n in names:
        key = (n or "").strip().lower()
        if not key:
            continue
        for a in have:
            if key == a["slug"].lower() or key == a["name"].lower() or key in a["name"].lower():
                if a not in out:
                    out.append(a)
                break
    return out
