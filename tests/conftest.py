"""Test bootstrap helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Deterministic Fernet key so crypto.encrypt/decrypt work in tests (mirrors prod AUTH_ENCRYPTION_KEY).
os.environ.setdefault("AUTH_ENCRYPTION_KEY", "l3mgT3MDKZ2g8oh2l8r4e1XaS0o7Q8mT9H5V1v3P2Hk=")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
