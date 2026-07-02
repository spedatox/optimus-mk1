"""
optimus/tui/brand.py

Single source of truth for brand identity and theme accent colour.
Both values are read from environment variables so the entire UI can be
re-themed and renamed without touching source code.

Environment variables
---------------------
OPTIMUS_ACCENT_COLOR   Hex colour used everywhere the accent appears.
                       Default: #4a9eff (bright terminal blue)

OPTIMUS_NAME           Product name shown in the UI (title, placeholder, help).
                       Default: Optimus
"""
from __future__ import annotations

import os

# ── Accent colour ─────────────────────────────────────────────────────────────
# Any valid CSS hex colour: #rrggbb or #rgb
ACCENT: str = os.environ.get("OPTIMUS_ACCENT_COLOR", "#4a9eff")

# ── Product name ──────────────────────────────────────────────────────────────
NAME: str = os.environ.get("OPTIMUS_NAME", "Optimus")
