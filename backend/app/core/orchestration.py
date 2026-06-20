"""Orchestration — where the multi-agent system stops being a single call.

This is the first place in the project where more than one agent call happens for a
single triage run, and the first place those calls happen *concurrently* rather than
one after another (CLAUDE.md Section 6, point 4: "genuine parallelism"). The Triage
Agent runs once and produces N scored arms; this layer fans a Question Generator
call out across the qualifying arms at the same time, not in sequence.
"""

import asyncio

from app.agents.question_generator import generate_questions
from app.config import QUESTION_GENERATION_THRESHOLD
from app.models import TriageOutput


async def populate_questions(
    triage_output: TriageOutput,
    chief_complaint: str,
    patient_context: str,
) -> TriageOutput:
    """Fill in history-taking questions for the arms that qualify, concurrently.

    Takes the whole `TriageOutput` in and returns the whole (updated) `TriageOutput`
    out — rather than returning just the new questions on their own — on purpose. The
    `TriageOutput` is the single coherent "current state of the interview" object as
    it moves through the pipeline: triage scores it, this step adds questions to it,
    and later the re-scoring loop (CLAUDE.md Section 6b) takes that same enriched
    object back in to revise scores. Threading one object through keeps that state in
    one place instead of scattering arms, scores, and questions across separate
    values that the caller has to reassemble.
    """
    # An arm qualifies for question generation only if the user hasn't pushed it down
    # AND triage scored it relevant enough. Below-threshold arms keep their already-
    # empty `questions` list — we simply never call the agent for them. That's the
    # cost/scope control (CLAUDE.md Section 5/6): question generation cost multiplies
    # by arm count, so we don't pay it for arms unlikely to matter.
    qualifying = [
        arm
        for arm in triage_output.arms
        if arm.status == "active"
        and arm.relevance_score >= QUESTION_GENERATION_THRESHOLD
    ]

    # The actual parallelism. asyncio.gather schedules every generate_questions()
    # coroutine at once and awaits them together; while each one is blocked on its
    # OpenRouter round-trip (which is I/O, not CPU — the event loop is free during
    # the wait), the others make progress. So N calls finish in roughly the wall-time
    # of the SLOWEST single call, not the sum of all N. A plain `for arm in
    # qualifying: await generate_questions(...)` would look almost identical but would
    # block on each call before starting the next, collapsing back to sequential and
    # silently breaking the Section 6 "genuine parallelism" claim. gather is what
    # makes the claim real. (It also preserves input order, so results line up with
    # `qualifying` positionally below.)
    results = await asyncio.gather(
        *(
            generate_questions(arm, chief_complaint, patient_context)
            for arm in qualifying
        )
    )

    # Attach each arm's questions back onto the arm. `qualifying` holds references to
    # the very same DiagnosticArm objects inside triage_output.arms, so assigning to
    # arm.questions updates the TriageOutput in place — non-qualifying arms are left
    # untouched with their empty lists.
    for arm, questions in zip(qualifying, results):
        arm.questions = questions

    return triage_output
