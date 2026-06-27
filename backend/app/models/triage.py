"""Triage Agent contracts: the agent's initial fan-out output, and the input
that re-triggers it when the user submits one or more answers from a card (the
feedback loop).
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


class AnsweredQuestion(BaseModel):
    """One newly-answered question within a re-scoring batch. Deliberately small —
    just enough for the Prioritization Agent to reason about what changed.

    Carries `question_text` alongside `question_id`/`answer_text` ON PURPOSE (a
    considered widening beyond the original two-field sketch): with the History Agent
    in place, an answered question may be a general-history question that does NOT
    live in any diagnostic arm, so the Prioritization Agent can NOT recover its text
    by scanning `current_arms`. The caller (`process_answers`) is the one place that
    can resolve text for BOTH sources (arm questions and the history checklist), so it
    resolves once and carries the text on the trigger — making the trigger fully
    self-describing and removing any need to re-resolve text downstream.
    """

    question_id: str
    answer_text: str
    question_text: str


class RescoreTrigger(BaseModel):
    """Input that kicks off a re-scoring call when the user submits one or more
    answers from a card. This is the input side of the feedback loop (CLAUDE.md
    Section 5, step 5).

    WIDENED from a single question_id/answer_text pair to a list of `new_answers`: a
    card-level submit may include several newly-answered questions at once, and the
    Prioritization Agent should reason about all of them together in ONE pass, not be
    called once per answer. A single-answer submission is just the
    `len(new_answers) == 1` case — no special-casing needed anywhere downstream.
    """

    # The batch of questions newly answered since the last re-score (one card's worth).
    new_answers: list[AnsweredQuestion]

    # The FULL current arm state, not just the new answers. Re-scoring is a *revision*
    # of prior scores and reasoning, not a fresh calculation from scratch — the agent
    # needs to see the existing scores/reasoning to adjust them. Passing the whole
    # state in is what makes this a genuine feedback LOOP (agents revising earlier
    # output) rather than a one-shot call (CLAUDE.md Section 5 step 5, Section 6
    # point 3).
    current_arms: list[DiagnosticArm]
