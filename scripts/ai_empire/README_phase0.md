# Jordan Phase 0 — Reference Set (fal.ai version of Ayurpet pipeline)

This is the exact Ayurpet Phase-0 process adapted for fal.ai (no MuAPI).

## Step 1: Generate face candidates
python plans/jordan_phase0_faces_fal.py --count 6 --model fal-ai/flux-pro/v1.1-ultra

Pick the single best "locked face" URL. This is your canonical Jordan.

## Step 2: Build reference sheet (the still images of the model)
python plans/jordan_phase0_refsheet_fal.py --face https://.../your-locked-face.jpg --download

This produces 6 consistent views (front, 3/4, profile, expressions) using strong i2i reference on fal Flux.
Put the downloaded images into assets/jordan/references/

These become the character_ref_set.

## Next (per Ayurpet plan)
- Train LoRA on fal: fal-ai/flux-lora-fast-training using the 6+ references.
- Or use the images directly as IP-Adapter / reference inputs in all future generations (Kling, Flux, etc.).
- The jordan_influencer_gen.py daily prompts should now reference these images for consistency.

See main Mesh Pilot docs/plans/2026-06-03-ai-influencer-pipeline.md for full context.
