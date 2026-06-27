"""Re-scoring orchestration — the feedback loop's glue.

This closes the loop CLAUDE.md Section 5 step 5 / Section 6 point 3 describe: the user
checking off an answer doesn't just update a flag, it re-triggers the Prioritization
Agent to REVISE the earlier triage scores. This module is what turns a single answer
into (a) an updated interview state and (b) the ScoreTransition records the Trace
Viewer (Section 6b) will later render — the visible proof the loop did something.
"""

import asyncio

from app.agents.prioritization import rescore_arms
from app.agents.suggestion_agent import suggest_questions
from app.core.orchestration import _active_arms, _qualifying_arms, ensure_arm_questions
from app.models import (
    AnsweredQuestion,
    ClinicalQuestion,
    Framework,
    HistoryAnswer,
    HistoryChecklist,
    RescoreTrigger,
    ScoreTransition,
    SuggestionBatch,
    TriageOutput,
    is_history_question_id,
)

# DATA-SOURCE CHANGE (multi-complaint generalization): the red-flag arm names used by
# the Prioritization Agent's safety check are no longer a module-level constant baked
# from the single hardcoded chest-pain framework. Frameworks are now per-complaint and
# resolved at request time, so the can't-miss set must be derived PER SESSION from the
# same `Framework` that was resolved for that interview — passed in via `process_answer`
# below. This is the exact seam the old "wired in directly" comment predicted. Behavior
# for chest pain is identical (the seeded chest-pain framework has the same red_flag
# arms); only WHERE the set comes from changed.


def _find_question(triage: TriageOutput, question_id: str) -> ClinicalQuestion | None:
    """Locate an ARM question by id across ALL arms. Ids are globally unique (namespaced
    per arm by the Question Generator), so the first match is the only match."""
    for arm in triage.arms:
        for question in arm.questions:
            if question.id == question_id:
                return question
    return None


def _find_history_question_text(
    history_checklist: HistoryChecklist | None, question_id: str
) -> str:
    """Recover a general-history question's text by id from the session's checklist.
    Fails loud if absent — same fail-loud principle as the arm path: we will not
    re-score against an answer whose question we can't identify."""
    if history_checklist is not None:
        for question in history_checklist.questions:
            if question.id == question_id:
                return question.question_text
    raise ValueError(
        f"history question_id '{question_id}' not found in this session's checklist."
    )


async def build_suggestions(
    triage: TriageOutput,
    framework: Framework,
    history_checklist: HistoryChecklist | None,
    history_answers: list[HistoryAnswer],
    transitions: list[ScoreTransition],
) -> SuggestionBatch:
    """Assemble the Suggestion Agent's inputs from session state and run it.

    The SINGLE wiring point both the interview start (`/api/triage`, no transitions yet)
    and the re-score path use, so the input assembly isn't duplicated. Active arms come
    from the shared `orchestration._active_arms` filter (NOT the top-N `_qualifying_arms`
    — the suggestion pool ranks across ALL active arms, not just the auto-generated
    top N); the red-flag arm names are derived from the framework, the same source the
    re-score safety check uses.
    """
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}
    return await suggest_questions(
        chief_complaint=triage.chief_complaint,
        active_arms=_active_arms(triage),
        history_checklist=history_checklist,
        history_answers=history_answers,
        red_flag_arm_names=red_flag_arm_names,
        transitions=transitions,
    )


def validate_answer_ids(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    history_checklist: HistoryChecklist | None,
) -> None:
    """Read-only pre-flight: confirm EVERY answer's question_id resolves (an arm question
    in the triage, or a history question in the checklist). Raises ValueError on the
    first miss.

    The streaming /api/answers route calls this BEFORE opening the event stream, so a
    bad question_id is rejected with a synchronous HTTP 400 rather than a mid-stream
    `error` frame — mirroring how the missing-session 404 stays a normal HTTP error.
    Pure and side-effect-free (it does not mark anything answered).
    """
    for question_id, _ in answers:
        if is_history_question_id(question_id):
            _find_history_question_text(history_checklist, question_id)  # raises if absent
        elif _find_question(current_triage, question_id) is None:
            raise ValueError(
                f"question_id '{question_id}' not found in the current triage state."
            )


async def apply_batch_and_rescore(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    framework: Framework,
    history_checklist: HistoryChecklist | None,
    history_answers: list[HistoryAnswer],
) -> tuple[TriageOutput, list[ScoreTransition]]:
    """Record a batch of answers and run the SINGLE re-score (the old steps 1-4).

    Factored out of `process_answers` so the streaming endpoint can emit a `rescored`
    stage event right after this returns — before suggestions are ranked — without
    duplicating any logic. Mutates in place exactly as before: arm questions are marked
    answered on `current_triage`, and history answers in the batch are appended to
    `history_answers` (the session's running list). `history_answers` must be a real
    list (the caller defaults it).

    Each AnsweredQuestion carries its resolved question_text so rescore_arms never has to
    re-resolve it (history questions aren't in the arm state). trigger_answer on each
    ScoreTransition holds the whole batch joined into one string (keeps the field a plain
    str so the Trace Viewer renders unchanged; a single-answer submit has no per-answer
    attribution to lose anyway).
    """
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}

    new_answers: list[AnsweredQuestion] = []
    for question_id, answer_text in answers:
        if is_history_question_id(question_id):
            question_text = _find_history_question_text(history_checklist, question_id)
            history_answers.append(
                HistoryAnswer(
                    id=question_id,
                    question_text=question_text,
                    answer_text=answer_text,
                )
            )
        else:
            question = _find_question(current_triage, question_id)
            if question is None:
                raise ValueError(
                    f"question_id '{question_id}' not found in the current triage state."
                )
            question.answered = True
            question.answer_text = answer_text
            question_text = question.text

        new_answers.append(
            AnsweredQuestion(
                question_id=question_id,
                answer_text=answer_text,
                question_text=question_text,
            )
        )

    trigger = RescoreTrigger(new_answers=new_answers, current_arms=current_triage.arms)
    updated_triage = await rescore_arms(
        trigger,
        chief_complaint=current_triage.chief_complaint,
        red_flag_arm_names=red_flag_arm_names,
        history_answers=history_answers,
    )

    batch_answer_text = "; ".join(a.answer_text for a in new_answers)
    old_scores = {arm.name: arm.relevance_score for arm in current_triage.arms}
    transitions = [
        ScoreTransition(
            arm_name=arm.name,
            old_score=old_scores[arm.name],
            new_score=arm.relevance_score,
            trigger_answer=batch_answer_text,
        )
        for arm in updated_triage.arms
        if arm.name in old_scores and old_scores[arm.name] != arm.relevance_score
    ]
    return updated_triage, transitions


async def promote_newly_qualified(
    prev_triage: TriageOutput,
    updated_triage: TriageOutput,
    patient_context: str,
) -> None:
    """Old step 5: after a re-score, any arm NEWLY in the auto-generate top N that still
    has no questions gets them generated now (mutates `updated_triage` arms in place).

    Factored out so the streaming endpoint can run it AFTER emitting `rescored` and
    BEFORE ranking suggestions — the suggestion pool must see the promoted arms'
    questions. We compare top-N membership by NAME (scores can tie; names are stable)
    between the pre-rescore state and the merged state.
    """
    old_top = {arm.name for arm in _qualifying_arms(prev_triage)}
    newly_promoted = [
        arm
        for arm in _qualifying_arms(updated_triage)
        if arm.name not in old_top and not arm.questions
    ]
    if newly_promoted:
        await asyncio.gather(
            *(
                ensure_arm_questions(arm, updated_triage.chief_complaint, patient_context)
                for arm in newly_promoted
            )
        )


async def process_answers(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    patient_context: str,
    framework: Framework,
    history_checklist: HistoryChecklist | None = None,
    history_answers: list[HistoryAnswer] | None = None,
) -> tuple[TriageOutput, list[ScoreTransition], SuggestionBatch]:
    """Apply a BATCH of answers, re-score ONCE, and rank suggestions — the plain
    (non-streaming) composition.

    This is the card-level submit semantics: a whole card costs exactly one
    Prioritization call regardless of how many questions were answered; a single-answer
    submit is just a one-element batch. Returns the updated `TriageOutput`, the
    `ScoreTransition` records, AND the re-ranked `SuggestionBatch`.

    It now COMPOSES the three reusable steps (`apply_batch_and_rescore` ->
    `promote_newly_qualified` -> `build_suggestions`) that the streaming /api/answers
    endpoint drives one-by-one with stage events in between — so the streaming and
    plain paths share identical logic and can't drift. The plain path is still used by
    the single-answer /api/answer route and the terminal pipeline runner.
    """
    if history_answers is None:
        history_answers = []

    updated_triage, transitions = await apply_batch_and_rescore(
        answers, current_triage, framework, history_checklist, history_answers
    )
    await promote_newly_qualified(current_triage, updated_triage, patient_context)
    suggestions = await build_suggestions(
        updated_triage, framework, history_checklist, history_answers, transitions
    )
    return updated_triage, transitions, suggestions
