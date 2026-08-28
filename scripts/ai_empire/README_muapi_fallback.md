# Fallback to MuAPI for Jordan Phase 0 (matching Ayurpet exactly)

We fell back to MuAPI (as in the main repo Ayurpet pipeline) because fal direct generations were still looking too AI-generated.

Scripts:
- plans/jordan_phase0_faces_muapi.py : Generate candidate faces using MuAPI (same as Ayurpet).
- plans/jordan_phase0_refsheet_muapi.py : From locked face, use nano-banana (MuAPI) to generate consistent reference views.

Usage:
1. Run faces: python3 plans/jordan_phase0_faces_muapi.py --count 6 --model flux-dev
2. Pick the best face URL from output.
3. Run refsheet: python3 plans/jordan_phase0_refsheet_muapi.py --face <picked-url>
4. Download the 6 ref images and place in assets/jordan/references/
5. Use these refs + the updated human-like prompt recipe in JORDAN_DAILY_ASSET_PROMPTS.md for all future content.

This should give the real-human look like the Ayurpet influencer.

See main repo: src/social_agent/scripts/influencer_phase0_*.py and docs/plans/2026-06-03-ai-influencer-pipeline.md
