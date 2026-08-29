"""Per-brand agent memory (AGENT-MEM) — facts + episodes with hybrid recall.

    from glitch_signal.agent.memory import remember, recall
"""
from __future__ import annotations

from glitch_signal.agent.memory.embeddings import EMBED_DIM, EmbeddingError, embed
from glitch_signal.agent.memory.spec import Memory
from glitch_signal.agent.memory.store import forget, recall, remember

__all__ = ["Memory", "remember", "recall", "forget", "embed", "EmbeddingError", "EMBED_DIM"]
