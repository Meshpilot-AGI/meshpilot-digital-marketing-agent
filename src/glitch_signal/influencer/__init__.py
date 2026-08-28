"""AI influencer pipeline — persona-driven synthetic creators.

See docs/plans/2026-06-03-ai-influencer-pipeline.md +
docs/plans/2026-06-03-ai-influencer-engagement-research.md.

End-to-end pipeline (brand-scoped, content_plan-driven):
  persona      — persona bible loader
  content_plan — core.influencer_post_plan store (idea→approved→…→posted)
  discovery    — collectors that fill the plan with ranked ideas
  muapi        — async multi-model generation client
  generate     — persona-consistent asset generation (locked refs)
  posting      — Upload-Post publish of generated assets
  engagement   — sanctioned owned-surface reply engine
  pipeline     — orchestrator ticks (discovery/generation/posting)
"""
from glitch_signal.influencer.persona import Persona, load_persona, list_personas  # noqa: F401
