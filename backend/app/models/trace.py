"""Trace contract: a single before/after record of one arm's score changing.

This model exists specifically so the re-scoring loop's internal state — which
*already* has to know "old score, new score, what caused it" in order to function
— has somewhere structured to land. The Agent Trace Viewer (CLAUDE.md Section 6b)
does NOT get its own storage or a separate event-logging system; it reads these
records directly. This is the deliberate "thin UI layer over state we already
track" decision, not new backend infrastructure.
"""

from pydantic import BaseModel, Field


class ScoreTransition(BaseModel):
    """One arm's relevance score moving from an old value to a new value, with the
    answer that caused the move."""

    # Which arm changed — matched by name to the arm in the current state.
    arm_name: str

    # The relevance score before the re-scoring call. Bounded to [0, 1] to mirror
    # DiagnosticArm.relevance_score — a transition is always built from real arm
    # scores, so the same constraint must hold here.
    old_score: float = Field(ge=0, le=1)

    # The relevance score after the re-scoring call. Same [0, 1] bound as
    # DiagnosticArm.relevance_score, for the same reason.
    new_score: float = Field(ge=0, le=1)

    # The answer text that caused this transition, so the Trace Viewer can render
    # "this answer caused this change," exactly matching the UI example in
    # CLAUDE.md Section 6b.
    trigger_answer: str
