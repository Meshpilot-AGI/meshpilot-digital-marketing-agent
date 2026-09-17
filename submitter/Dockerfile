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
# NOBLE, not jammy. The jammy image is Ubuntu 22.04 with python3.10, and this package declares
# `requires-python = ">=3.11"`, so `pip install .` fails with
# `requires a different Python: 3.10.12 not in '>=3.11'`. Noble is Ubuntu 24.04 with python3.12
# (verified from the image config, not assumed). Bump this tag deliberately — Playwright pins the
# browser build to the image, so the tag IS the Chromium version.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

WORKDIR /app

# Ubuntu 24.04 ships PEP 668 "externally-managed-environment", which refuses `pip install` into the
# system Python. This image's whole purpose is running one app, and Playwright itself lives in that
# same system Python, so installing alongside it is the intended shape — not a workaround around a
# shared machine. Set as an env var rather than a flag so it applies to every pip call, and it is a
# harmless no-op on an image without the marker.
ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# Install the agent package itself, so the submitter shares ONE copy of the store, the submission
# guards and the fact verifier. A second implementation of those rules is how the guards drift apart.
# pyproject declares `readme = "README.md"` and `license = { file = "LICENSE" }`, and hatchling
# VALIDATES both at build time — a missing LICENSE fails the install with
# `OSError: License file does not exist`. Copy every file the metadata references, not just the
# obvious two.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# ⚠️ Playwright's PYTHON BINDINGS, pinned to this image's tag. The image ships Chromium and its
# system libraries, and it ships playwright for the interpreter IT was built around — but
# `pip install .` above lands our package in /usr/local/lib/python3.12/dist-packages, and from
# there `import playwright` did not resolve: the submitter rendered the CV fine and then failed
# every pass with "No module named 'playwright'" (observed live 2026-09-16, Railway).
#
# The version MUST track the FROM tag above (v1.55.0-noble → 1.55.0). Playwright refuses to drive a
# browser build it does not recognise, so a drifting pin breaks the one thing this container exists
# to do. Bump both lines together or not at all.
RUN pip install --no-cache-dir "playwright==1.55.0" \
 && python -c "import playwright, sys; print('playwright', playwright.__version__ if hasattr(playwright,'__version__') else 'ok', 'importable on', sys.executable)"

COPY submitter/worker.py ./worker.py

# No inbound HTTP. This is a poll loop.
CMD ["python", "-u", "worker.py"]
