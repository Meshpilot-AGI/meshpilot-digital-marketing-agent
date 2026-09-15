# MeshPilot job submitter — the ONLY container with a browser (Railway).
#
# It exists because neither Greenhouse nor Lever offers a candidate-side application API: both
# application POSTs require the EMPLOYER's key, so a candidate must drive the public web form.
# FastAPI Cloud (where the API runs) builds from Python standards with no way to install Chromium's
# system libraries, so the browser lives here instead — the same place the Discord gateway already
# runs, with a Dockerfile we control.
#
# Playwright's own image ships Chromium AND its system deps, which is the whole reason to use it
# rather than python:slim + a long apt incantation that drifts.
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

# Install the agent package itself, so the submitter shares ONE copy of the store, the submission
# guards and the fact verifier. A second implementation of those rules is how the guards drift apart.
# pyproject declares `readme = "README.md"` and `license = { file = "LICENSE" }`, and hatchling
# VALIDATES both at build time — a missing LICENSE fails the install with
# `OSError: License file does not exist`. Copy every file the metadata references, not just the
# obvious two.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY submitter/worker.py ./worker.py

# No inbound HTTP. This is a poll loop.
CMD ["python", "-u", "worker.py"]
