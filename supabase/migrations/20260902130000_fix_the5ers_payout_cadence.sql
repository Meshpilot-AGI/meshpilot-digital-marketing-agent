-- Correct a verified fact that was rendering as nonsense.
--
-- The first agent-authored blog post contained: "The5ers High Stakes lists payout cadence as every
-- 0 days". That was faithful to our row (`value_num = 0`, `value_text = 'payouts every 0 days'`) —
-- grounding guarantees fidelity to our data, not the correctness of it.
--
-- The source of truth is the app's own engine table, `shared/risk/firmRules.ts`, and it turns out
-- **0 is a deliberate sentinel, not a missing value**:
--
--     // - On-demand payouts on the funded stage
--     payoutCadenceDays: 0,
--
-- Every other firm carries 14 (bi-weekly). The5ers pays on demand, which is a genuinely useful fact
-- and a real differentiator — it should be stated, not suppressed and not rendered as a zero-day
-- cycle. `value_num` stays 0 because that IS the engine's sentinel and the survival/payout widgets
-- read it; only the human-readable text is wrong.
update firm_rule
   set value_text = 'on-demand payouts (no fixed cadence)',
       caveat     = 'payoutCadenceDays is 0 in the engine table as a sentinel for on-demand, '
                    'not a zero-day cycle'
 where firm_id = 'the5ers'
   and rule_key = 'payout_cadence';
