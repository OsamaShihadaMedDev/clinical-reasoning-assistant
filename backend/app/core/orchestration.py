"""Orchestration — where the multi-agent system stops being a single call.

This is the first place in the project where more than one agent call happens for a
single triage run, and the first place those calls happen *concurrently* rather than
one after another (CLAUDE.md Section 6, point 4: "genuine parallelism"). The Triage
Agent runs once and produces N scored arms; this layer fans a Question Generator
call out across the qualifying arms at the same time, not in sequence.

Two callers, same concurrency, different *delivery*:
- `populate_questions()` — fans out, waits for ALL arms, returns one full TriageOutput.
- `populate_questions_streaming()` — fans out the SAME way, but yields each arm's
  questions the moment that arm finishes, so a streaming endpoint (SSE) can reveal
  arm cards progressively instead of after one long all-or-nothing pause.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable

from app.agents.question_generator import generate_questions
from app.config import TOP_N_AUTO_GENERATE
from app.models import ClinicalQuestion, DiagnosticArm, TriageOutput


def _qualifying_arms(triage_output: TriageOutput) -> list[DiagnosticArm]:
    """The arms that get questions auto-generated: the top `TOP_N_AUTO_GENERATE`
    ACTIVE arms by score.

    Shared by both population functions AND the post-rescore top-N check in
    `rescore.py`, so the "which arms auto-generate" rule lives in exactly one place
    (CLAUDE.md: prefer reusing one selection function over parallel copies). Two gates,
    in order: status first (a deprioritized arm never qualifies, regardless of score),
    then rank (only the N highest-scoring of what's left). Every other active arm keeps
    its already-empty `questions` list and is generated LAZILY instead — on demand when
    the user expands it, or automatically if a re-score later lifts it into the top N
    (see `ensure_arm_questions`). That's the cost/scope control (CLAUDE.md Section 5/6):
    question generation cost multiplies by arm count, so we don't pay it up front for
    arms nobody is looking at yet.
    """
    active = [arm for arm in triage_output.arms if arm.status == "active"]
    # Sort by score descending; ties resolve by the arms' existing order (Python's sort
    # is stable), which is good enough — the cutoff at N is a cost heuristic, not a
    # clinically meaningful boundary, and a re-score re-evaluates membership anyway.
    active.sort(key=lambda arm: arm.relevance_score, reverse=True)
    return active[:TOP_N_AUTO_GENERATE]


async def ensure_arm_questions(
    arm: DiagnosticArm,
    chief_complaint: str,
    patient_context: str,
) -> list[ClinicalQuestion]:
    """Ensure ONE arm has questions, generating them only if it has none yet.

    The single shared "generate questions for an arm if missing" primitive. It is
    called from THREE places — the initial top-N fan-out (below), the on-demand expand
    endpoint, and the post-rescore top-N check (`rescore.py`) — so the "already has
    questions -> do nothing" guard and the in-place mutation live in exactly one place.
    That's deliberate (per the task): three call sites must not drift into three
    slightly different ideas of what "ensure questions" means (e.g. one accidentally
    regenerating and duplicating).

    Idempotent by design: if `arm.questions` is already non-empty it returns them
    unchanged and makes NO agent call — so callers (especially a frontend hitting the
    expand endpoint defensively) can call it without first checking. Mutates the arm in
    place so the enclosing `TriageOutput` is updated wherever this arm lives, and also
    returns the list for callers that want it directly.
    """
    if arm.questions:
        return arm.questions
    arm.questions = await generate_questions(arm, chief_complaint, patient_context)
    return arm.questions


async def _with_arm(
    arm: DiagnosticArm,
    coro: Awaitable[list[ClinicalQuestion]],
) -> tuple[DiagnosticArm, list[ClinicalQuestion]]:
    """Run one question-generation coroutine and tag its result with its arm.

    Needed only for the streaming path: `asyncio.as_completed` yields results in
    COMPLETION order, which destroys the positional `qualifying[i] -> result[i]`
    correspondence that `gather` preserves. Pairing the arm to its own result up
    front means we still know which arm a result belongs to when it comes back out of
    order.
    """
    questions = await coro
    return arm, questions


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
    qualifying = _qualifying_arms(triage_output)

    # The actual parallelism. asyncio.gather schedules every ensure_arm_questions()
    # coroutine at once and awaits them together; while each one is blocked on its
    # OpenRouter round-trip (which is I/O, not CPU — the event loop is free during
    # the wait), the others make progress. So N calls finish in roughly the wall-time
    # of the SLOWEST single call, not the sum of all N. A plain `for arm in
    # qualifying: await ensure_arm_questions(...)` would look almost identical but would
    # block on each call before starting the next, collapsing back to sequential and
    # silently breaking the Section 6 "genuine parallelism" claim. gather is what
    # makes the claim real. `ensure_arm_questions` mutates each arm in place (and these
    # are the same DiagnosticArm objects inside triage_output.arms), so we don't need
    # the results here — non-qualifying arms are simply left with their empty lists.
    await asyncio.gather(
        *(
            ensure_arm_questions(arm, chief_complaint, patient_context)
            for arm in qualifying
        )
    )

    return triage_output


async def populate_questions_streaming(
    triage_output: TriageOutput,
    chief_complaint: str,
    patient_context: str,
) -> AsyncIterator[tuple[DiagnosticArm, list[ClinicalQuestion]]]:
    """Same concurrent fan-out as `populate_questions()`, but yield each arm's
    questions the instant that arm finishes — completion order, not start order.

    The ONLY difference from the batch version is WHEN each piece becomes available:
    `as_completed` runs the identical set of concurrent coroutines (the parallelism is
    unchanged — it does NOT serialize anything), but hands each result back as soon as
    it lands instead of holding everything until the slowest call returns. This is
    what lets the SSE endpoint reveal arm cards progressively.

    Like `populate_questions()`, this still mutates `arm.questions` in place as each
    arm completes — so once the generator is exhausted the original `TriageOutput` is
    fully populated and can be stored/used as the complete interview state. Callers get
    both: the progressive (arm, questions) stream AND, afterward, the finished object.
    """
    qualifying = _qualifying_arms(triage_output)

    # Wrap each call so its result arrives tagged with its arm (see `_with_arm`).
    # ensure_arm_questions does the in-place mutation and the empty-check; here every
    # qualifying arm starts empty (initial triage), so each one really does generate.
    pending = [
        _with_arm(arm, ensure_arm_questions(arm, chief_complaint, patient_context))
        for arm in qualifying
    ]

    for finished in asyncio.as_completed(pending):
        arm, questions = await finished
        yield arm, questions
