"""The fact base — the ONLY source for claims about the operator.

Design § 5. This mirrors career-ops' Source-of-Truth Boundary, and it exists because a tailored CV
that invents a number is worse than no CV: it is a lie told in the operator's name, to a hiring
manager, at scale.

PRIMARY (full trust): the brand's `jobs.cv_markdown` / `cv_path`, and the brand config itself.
Everything else — past tailored CVs, episodes, memory, other repos on the machine — is out of scope
for generated content. Memory steers BEHAVIOUR; it never supplies facts about the operator's work.
"""
from __future__ import annotations

from pathlib import Path


def cv_text(brand_id: str, cfg: dict | None = None) -> str:
    """The operator's master CV for this brand. Empty string when none is configured.

    Deliberately returns '' rather than falling back to memory, a previous tailored CV, or anything
    outside the primary set: an empty fact base must fail loudly upstream, not quietly source
    claims from somewhere unvetted.
    """
    from glitch_signal.config import brand_config

    cfg = cfg if cfg is not None else ((brand_config(brand_id) or {}).get("jobs") or {})
    inline = cfg.get("cv_markdown")
    if isinstance(inline, str) and inline.strip():
        return inline.strip()
    path = cfg.get("cv_path")
    if path:
        p = Path(path).expanduser()
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return ""
