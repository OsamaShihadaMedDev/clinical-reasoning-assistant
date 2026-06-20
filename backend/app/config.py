"""Application configuration.

Loads environment variables from .env and exposes them as module-level
constants. Kept intentionally minimal for the scaffolding step.
"""

import os

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Per-agent model routing (CLAUDE.md Section 7). Triage and Question Generator
# are called frequently per session (initial fan-out + every re-score), so they
# route to a cheap/fast model. Prioritization/Red-Flag is safety-critical and
# called less often, so it routes to a stronger model. Naming these as roles,
# not raw model strings scattered through the codebase, is what makes it
# possible to swap a model for one agent without touching call sites.

TRIAGE_MODEL = "anthropic/claude-haiku-4.5"
QUESTION_GENERATOR_MODEL = "anthropic/claude-haiku-4.5"
PRIORITIZATION_MODEL = "anthropic/claude-sonnet-4.5"

# CLAUDE.md Section 5/6: originally a cost-control gate so only meaningfully
# relevant arms got questions generated. After testing, the decision was made
# to generate questions for every active arm regardless of score (0.05 is
# effectively "always," since arms rarely score below it) — full fan-out is
# the actual product behavior going forward, not just a demo setting.
# DiagnosticArm.status still gates participation: a deprioritized arm gets
# no questions until the user reactivates it. If a future UI reintroduces a
# manual "generate questions for this low-relevance arm" action, that's a
# DIFFERENT mechanism than this threshold (which no longer meaningfully
# filters anything) — don't conflate the two.
QUESTION_GENERATION_THRESHOLD = 0.05
