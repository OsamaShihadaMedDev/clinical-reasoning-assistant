"""Suggestion Agent contracts: the clinician-facing "what to ask next" pool.

The Suggestion Agent does NOT generate questions or diagnose — it SELECTS, from the
questions other agents already produced (arm questions + general-history questions),
the small set most worth surfacing right now, and ranks them. This is the contract for
that ranked output.

Pattern notes (consistent with the rest of app/models):
- `SuggestedQuestion` co-locates its `justification` with the thing it justifies, the
  same way `DiagnosticArm` keeps `reasoning` next to `relevance_score` (see
  clinical.py's module docstring). The justification here is deliberately ONE short
  line, not the paragraph-length `arm.reasoning` — this is the terse card label; the
  long explanation stays on the arm.
- There is deliberately NO numeric "suggestion score". Unlike DiagnosticArm, this
  output is a RANKING (an ordered list), not a set of independently-scored items: the
  agent's job is "pick and order N", not "score every candidate". A fake score field
  to sort by would be exactly the meaningless-number drift history.py warns against
  for HistoryAnswer. The list ORDER is the ranking — do not re-sort downstream.
"""

from pydantic import BaseModel


class SuggestedQuestion(BaseModel):
    """One question the Suggestion Agent picked to surface in the clinician-facing
    pool, with its one-line justification co-located (same pattern as
    DiagnosticArm.relevance_score + .reasoning)."""

    # References an EXISTING question already generated elsewhere — a ClinicalQuestion.id
    # (arm question) or a HistoryQuestion.id (general history). This agent does NOT
    # generate new question text; it only selects and justifies. Validated in code
    # against the candidate pool after the call — a model-invented id is dropped.
    question_id: str

    # The literal question text, copied at suggestion time so the frontend renders the
    # card without a second lookup. Authoritative copy comes from the pool in code (not
    # the model's echo), mirroring how rescore.py resolves question_text once in code.
    question_text: str

    # Arm name(s) this question is relevant to. A LIST because one question can serve
    # more than one arm (e.g. a bowel/bladder question matters to Cauda Equina AND
    # general red-flag screening). Empty for general-history questions (not tied to any
    # arm). Computed in code: the question's home arm plus any additional real arms the
    # model named (invented arm names dropped).
    source_arms: list[str]

    # One short clinical line shown on the card, e.g. "would localize nerve root level."
    # Intentionally terse (contrast arm.reasoning's longer, expandable text).
    justification: str

    # True if any of source_arms is a red-flag (can't-miss) arm. Drives the frontend's
    # danger-tinted treatment. Computed in CODE from the framework's red-flag arm names
    # (the same source rescore.py uses) — never a model-emitted boolean.
    is_red_flag: bool

    # True if this is a general-history question rather than an arm question. The
    # frontend needs it to route the answer the same way /api/answers already does by id.
    # Computed in CODE via is_history_question_id — never a model-emitted boolean.
    is_history_question: bool


class SuggestionBatch(BaseModel):
    """The full ranked output of one Suggestion Agent call. Ranked top-to-bottom by the
    agent's own ordering — do NOT re-sort downstream by a numeric score (there isn't
    one; see the module docstring). The list order IS the ranking."""

    suggestions: list[SuggestedQuestion]
