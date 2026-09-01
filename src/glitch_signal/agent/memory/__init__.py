"""Per-brand agent memory (AGENT-MEM) — facts + episodes with hybrid recall.

    from glitch_signal.agent.memory import remember, recall
"""
from __future__ import annotations

from glitch_signal.agent.memory.embeddings import EMBED_DIM, EmbeddingError, embed
from glitch_signal.agent.memory.spec import Memory
from glitch_signal.agent.memory.store import (
    forget,
    is_verified_provenance,
    list_memories,
    recall,
    remember,
    set_verified,
    unset_verified,
)

__all__ = [
    "Memory", "remember", "recall", "forget", "embed", "EmbeddingError", "EMBED_DIM",
    "list_memories", "set_verified", "unset_verified", "is_verified_provenance",
]
