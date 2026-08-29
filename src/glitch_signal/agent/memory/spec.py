"""Memory transport shape (AGENT-MEM)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Kind = Literal["fact", "episode"]


@dataclass(slots=True)
class Memory:
    id: str
    brand_id: str
    kind: Kind
    content: str
    key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    source: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    # Populated by recall(): fused relevance score + its parts (0..1).
    score: float | None = None
    semantic: float | None = None
    lexical: float | None = None
