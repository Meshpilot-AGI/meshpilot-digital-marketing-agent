# Ayurpet pipeline adapted for Jordan + fal.ai

Same structure as main repo Ayurpet pilot:

Phase 0 (build the model stills / character_ref_set):

1. Generate candidates
   FAL_KEY=... python plans/jordan_phase0_faces_fal.py --count 6 --model fal-ai/flux-pro/v1.1-ultra

   Pick the best face URL (this is your locked Jordan).

2. Build reference sheet (the "still Images of the model")
   FAL_KEY=... python plans/jordan_phase0_refsheet_fal.py --face <picked-url> --download

   Produces 6 consistent views using fal i2i reference (strong identity lock like MuAPI nano-banana).

   They go to assets/jordan/references/

3. Use forever
   - In all prompts: start with the LOCKED_BASE
   - Pass the ref images as image references to fal Flux / Kling / Comfy etc.
   - (Recommended) Train one LoRA on the set with fal-ai/flux-lora-fast-training

The jordan_influencer_gen.py is the daily planner (scout/plan part) — it already follows the Ayurpet pattern.

Full loop details: main monorepo docs/plans/2026-06-03-ai-influencer-pipeline.md

Now you have the exact pipeline, just fal instead of MuAPI.
