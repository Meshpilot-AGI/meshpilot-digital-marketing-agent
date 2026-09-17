-- JOBS-23 — an error on OUR side must not consume the operator's approval.
--
-- Measured 2026-09-17: a placement defect in the Greenhouse driver set two APPROVED applications to
-- `failed`. The operator's decision was spent by our bug, and nothing could retry them once it was
-- fixed — the cards had to be re-offered and re-approved, and an approval card expires in 48h.
--
-- `manual_required` is different and must keep demoting: it means the FORM asked something the
-- operator has not answered, which is a decision only they can make.
alter table job_application add column if not exists attempts integer not null default 0;

comment on column job_application.attempts is
  'Submission attempts that failed on OUR side (driver error, timeout). Bounded retry. A manual_required outcome is the operator''s decision and does not count here.';
