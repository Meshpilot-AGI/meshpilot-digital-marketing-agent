-- Correct the unit metadata on existing MUapi balance_snapshots rows.
--
-- MUapi's balance was always denominated in DOLLARS, not credits — the reconciliation code was
-- fixed to record new snapshots with balance_unit='usd' (see reconcile.py's BALANCE_UNIT), but
-- every row inserted before that fix is still labelled 'credits'. That leaves the audit trail with
-- mixed, partially-wrong units for the same vendor: a historical comparison against those rows
-- would still misread them as 100x smaller than they actually are.
--
-- The numeric `balance` values themselves need no conversion — MUapi never reported credits, so the
-- stored numbers were always genuinely dollars, only the label was wrong. Only balance_unit changes.
update balance_snapshots
   set balance_unit = 'usd'
 where vendor = 'muapi'
   and balance_unit = 'credits';
