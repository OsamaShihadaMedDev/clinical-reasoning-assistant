"""Application configuration.

Loads environment variables from .env and exposes them as module-level
constants. Kept intentionally minimal for the scaffolding step.
"""

import os

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# NOTE: Per-agent model routing constants will live here in a future session.
# Planned shape (see CLAUDE.md Section 7):
#   - Triage Agent          -> Haiku-class (cheap/fast, frequent calls)
#   - Question Generator     -> Haiku-class (cheap/fast, ×N parallel)
#   - Prioritization/Red-Flag -> Sonnet-class or better (safety-critical)
# Do NOT build the routing logic yet — just leaving this marker.
