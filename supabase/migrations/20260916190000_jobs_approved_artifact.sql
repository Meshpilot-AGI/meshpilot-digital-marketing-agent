-- JOBS-12 — bind an approval to the artifact it approved.
--
-- The operator approves a SPECIFIC tailored CV shown on the Discord card. Until now that markdown
-- existed only in the card: `hunt.run` generated it, verified it, rendered it into the card text and
-- dropped it. `tailored_cv_path` stayed NULL. So a later submission would have re-tailored and sent
-- a DIFFERENT document than the one approved — the gate would have been theatre.
--
-- Markdown rather than the PDF path on purpose: the PDF is derived and `render_cv_pdf` writes to
-- local disk, which is ephemeral on FastAPI Cloud, so a stored path would rot. The markdown is the
-- source of truth and re-renders deterministically.
alter table job_application add column if not exists tailored_cv_md text;

-- Who approved it. `read_decision` already identified the approving user to check them against the
-- allowlist, then discarded the id — so every approval recorded WHO as NULL. On the one action in
-- this system that is irreversible and taken in the operator's name, "someone on the allowlist"
-- is a weaker audit trail than the code could trivially provide.
comment on column job_application.approved_by is
  'Discord user id of the approver, from the reaction that decided the card.';
