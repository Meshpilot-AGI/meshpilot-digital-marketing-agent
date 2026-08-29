"""Playbook library — the agent's domain-knowledge handbooks.

A playbook is reference craft the agent *reads* to do specialized marketing work well (audit an ads
account, write a per-platform caption, run an SEO audit, respond to ORM). Distinct from media
recipes, which are *executed*. Each ships as `library/<slug>/SKILL.md` with YAML frontmatter:

    ---
    name: <slug>
    description: <one line — what it teaches + when to use it>
    ---
    # ... the handbook body ...

The agent lists playbooks (name + description) and reads the one it needs on demand — progressive
disclosure, so the system prompt stays lean.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

LIBRARY_DIR = Path(__file__).resolve().parent / "library"


@dataclass(frozen=True, slots=True)
class Playbook:
    slug: str
    name: str
    description: str
    body: str


def _parse(path: Path) -> Playbook:
    text = path.read_text(encoding="utf-8")
    name = path.parent.name
    description = ""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm, body = text[3:end], text[end + 4:].lstrip("\n")
            for line in fm.splitlines():
                if line.startswith("name:"):
                    name = line[5:].strip() or name
                elif line.startswith("description:"):
                    description = line[12:].strip()
    return Playbook(slug=path.parent.name, name=name, description=description, body=body.strip())


@functools.lru_cache(maxsize=1)
def _library() -> dict[str, Playbook]:
    out: dict[str, Playbook] = {}
    if not LIBRARY_DIR.is_dir():
        return out
    for skill in sorted(LIBRARY_DIR.glob("*/SKILL.md")):
        try:
            pb = _parse(skill)
            out[pb.slug] = pb
        except Exception:  # noqa: BLE001 — one malformed playbook never breaks the library
            continue
    return out


def list_playbooks() -> list[Playbook]:
    return list(_library().values())


def get_playbook(slug: str) -> Playbook | None:
    return _library().get(slug)
