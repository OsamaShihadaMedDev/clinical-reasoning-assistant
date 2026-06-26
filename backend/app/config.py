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

# Routing for the Framework Agent (backend/app/agents/framework_agent.py), which
# runs BEFORE triage to resolve a diagnostic-arm framework for the chief complaint.
# Two very different call profiles, so two different tiers:

# The semantic-match check ("does this new complaint match an already-cached one?")
# runs on EVERY single request and is a low-stakes judgment call — comparing a short
# complaint string against a short list of cached names. Same tier reasoning as
# TRIAGE_MODEL: cheap/fast, called frequently.
FRAMEWORK_MATCH_MODEL = "anthropic/claude-haiku-4.5"

# Called once EVER per genuinely new complaint; the result is cached permanently and
# every future patient with this complaint inherits this one call's quality. There is
# no per-request chance to course-correct the way Triage gets re-run on every request,
# so the one generation must be as good as we can make it — and at this call frequency
# (essentially never, after the first few complaints) cost is irrelevant. Routed to
# the strongest available model, deliberately at or above PRIORITIZATION_MODEL's tier,
# not merely matching it.
FRAMEWORK_GENERATION_MODEL = "anthropic/claude-opus-4.6"

# CLAUDE.md Section 5/6: how many arms get questions auto-generated at initial
# triage. History of this decision (don't re-litigate the earlier steps):
#   1. Originally a score THRESHOLD (QUESTION_GENERATION_THRESHOLD = 0.4) — a
#      cost-control gate so only meaningfully relevant arms got questions.
#   2. Lowered to 0.05 ("effectively always") to force a full concurrent
#      fan-out, then kept there as the real behavior for a while.
#   3. Now replaced by a TOP-N rule: only the top N ACTIVE arms BY SCORE get
#      questions generated automatically. The rest arrive with an empty
#      questions list and are generated lazily — on demand when the user expands
#      an arm, and automatically if a re-score pushes an arm into the top N
#      (see orchestration.ensure_arm_questions + the /api/arm/expand route).
# Why the change: full fan-out generated real OpenRouter calls for arms nobody
# was looking at (e.g. a 3%-relevance Panic arm getting 5 unasked-for questions)
# — a cost AND a UX problem. Top-N + lazy generation pays the cost only for arms
# that are actually relevant or actually requested.
# DiagnosticArm.status still gates participation independently: a deprioritized
# arm gets NO questions regardless of score until the user reactivates it.
TOP_N_AUTO_GENERATE = 3
