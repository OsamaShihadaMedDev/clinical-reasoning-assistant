"""Triage Agent contracts: the agent's initial fan-out output, and the input
that re-triggers it when the user answers a question (the feedback loop).
"""

from pydantic import BaseModel

from app.models.clinical import DiagnosticArm


class TriageOutput(BaseModel):
    """What the Triage Agent returns on the initial fan-out, before any question
    generation has happened."""

    # The original complaint that triggered this triage. Kept ON the output so
    # downstream consumers (Question Generator, re-scoring, summary panel) don't have
    # to thread the complaint through separately alongside the arms.
    chief_complaint: str

    # The scored, reasoned diagnostic arms. At THIS stage every arm's `questions`
    # list is empty: the Triage Agent's narrow scope is to score and justify arms
    # only — it does NOT generate questions (CLAUDE.md Section 6, point 1: one
    # narrow responsibility per agent). Question population is a separate step.
    arms: list[DiagnosticArm]


class RescoreTrigger(BaseModel):
    """Input that kicks off a re-scoring call when the user checks off an answer.
    This is the input side of the feedback loop (CLAUDE.md Section 5, step 5)."""

    # Which question was just answered — matched back to a ClinicalQuestion by id.
    question_id: str

    # What the user entered/selected as the answer. This new piece of state is what
    # the Triage Agent reasons over to decide how arm relevance should shift.
    answer_text: str

    # The FULL current arm state, not just the new answer. Re-scoring is a *revision*
    # of prior scores and reasoning, not a fresh calculation from scratch — the agent
    # needs to see the existing scores/reasoning to adjust them. Passing the whole
    # state in is what makes this a genuine feedback LOOP (agents revising earlier
    # output) rather than a one-shot call (CLAUDE.md Section 5 step 5, Section 6
    # point 3).
    current_arms: list[DiagnosticArm]
