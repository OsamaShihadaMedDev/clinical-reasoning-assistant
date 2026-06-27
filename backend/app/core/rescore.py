"""Re-scoring orchestration — the feedback loop's glue.

This closes the loop CLAUDE.md Section 5 step 5 / Section 6 point 3 describe: the user
checking off an answer doesn't just update a flag, it re-triggers the Prioritization
Agent to REVISE the earlier triage scores. This module is what turns a single answer
into (a) an updated interview state and (b) the ScoreTransition records the Trace
Viewer (Section 6b) will later render — the visible proof the loop did something.
"""

import asyncio

from app.agents.prioritization import rescore_arms
from app.core.orchestration import _qualifying_arms, ensure_arm_questions
from app.models import (
    AnsweredQuestion,
    ClinicalQuestion,
    Framework,
    HistoryAnswer,
    HistoryChecklist,
    RescoreTrigger,
    ScoreTransition,
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


async def process_answers(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    patient_context: str,
    framework: Framework,
    history_checklist: HistoryChecklist | None = None,
    history_answers: list[HistoryAnswer] | None = None,
) -> tuple[TriageOutput, list[ScoreTransition]]:
    """Apply a BATCH of answered questions to the interview and re-score ONCE.

    This is the card-level-submit version: a clinician fills several fields in one card
    and submits them together, so a whole card costs exactly ONE Prioritization call
    regardless of how many questions were answered. A single-answer submit is just the
    one-element batch (`len(answers) == 1`) — no special-casing.

    Returns the updated `TriageOutput` AND the `ScoreTransition` records for arms whose
    score actually moved (what the Trace Viewer renders).

    ONE re-score path, TWO input shapes per item. Each answered question is EITHER an
    arm question OR a general-history question; we tell them apart by the id alone
    (`is_history_question_id`) and branch ONLY on how each item is recorded — there is
    still exactly one Prioritization call for the whole batch:
      - ARM answer:     mark the ClinicalQuestion answered in place (as before).
      - HISTORY answer: record a HistoryAnswer into `history_answers` (the session's
                        accumulating list). Not part of any arm, so nothing in
                        `current_triage` is mutated for it.
    Every item is also added to the trigger's `new_answers` batch (each carrying its
    resolved question_text), and the full `history_answers` list is always handed to
    rescore_arms as background context.

    `patient_context` is threaded through because a re-score can change WHICH arms are
    in the auto-generated top N: if the batch lifts a previously-quiet arm into the top
    N, we generate its questions here (using the same patient context the initial
    fan-out used) so the caller gets one fully-consistent state.

    `framework` is this session's resolved diagnostic-arm framework, used to derive the
    red-flag (can't-miss) arm names per session (see the DATA-SOURCE CHANGE note above).

    `history_checklist` / `history_answers` are this session's general-history state;
    they default to None/[] so non-history callers (e.g. the terminal pipeline runner)
    can ignore them. NOTE: history answers in the batch are appended to the SAME
    `history_answers` list object the caller passed, so the caller's session reflects
    them without a separate return value.
    """
    if history_answers is None:
        history_answers = []

    # Per-session red-flag set: the time-critical arms the Prioritization Agent's
    # safety check must never let silently sink. Derived from THIS session's framework.
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}

    # 1. Record EVERY answer in the batch, branching by TYPE, and assemble the trigger
    #    batch. Each AnsweredQuestion carries its resolved question_text so rescore_arms
    #    never has to re-resolve it (history questions aren't in the arm state).
    new_answers: list[AnsweredQuestion] = []
    for question_id, answer_text in answers:
        if is_history_question_id(question_id):
            # General-history answer: not in any arm. Capture it as a HistoryAnswer and
            # add it to the session's running list (also handed to rescore_arms below).
            question_text = _find_history_question_text(history_checklist, question_id)
            history_answers.append(
                HistoryAnswer(
                    id=question_id,
                    question_text=question_text,
                    answer_text=answer_text,
                )
            )
        else:
            # Arm answer: mark the ClinicalQuestion answered in place, so the answered
            # flag/text travel with the arm and survive the re-score (which preserves
            # questions).
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

    # 2. Build ONE trigger carrying the whole batch + the full current arm state.
    trigger = RescoreTrigger(new_answers=new_answers, current_arms=current_triage.arms)

    # 3. Re-score ONCE for the whole batch. The agent reasons over all new answers
    #    jointly (see prioritization.py's batch instruction).
    updated_triage = await rescore_arms(
        trigger,
        chief_complaint=current_triage.chief_complaint,
        red_flag_arm_names=red_flag_arm_names,
        history_answers=history_answers,
    )

    # 4. Compute ScoreTransitions IN CODE by diffing old vs new scores per arm name —
    #    never trust the model to self-report what changed, since the delta is a fact we
    #    can compute directly and verify. Only emit a transition for arms that actually
    #    moved. trigger_answer holds the batch joined into one string (the simpler of
    #    the two options considered — keeps ScoreTransition.trigger_answer a plain str,
    #    so the Trace Viewer renders unchanged; the tradeoff is it loses the one
    #    answer -> one move mapping, which a single-answer submit doesn't have anyway).
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

    # 5. Re-evaluate the auto-generate top N AFTER merging the new scores. The top N is
    #    NOT fixed at initial triage — a re-score can promote a previously-quiet arm
    #    into it (e.g. a pleuritic answer lifting Pulmonary Embolism above Cardiac). Any
    #    arm that is newly in the top N AND still has no questions gets them generated
    #    now, as part of THIS call, via the same `ensure_arm_questions` primitive the
    #    on-demand endpoint uses — so the system-triggered and click-triggered paths
    #    are one mechanism, not two. We compare membership by NAME (scores can tie, but
    #    names are unique and stable). `ensure_arm_questions` mutates arms in place and
    #    they belong to `updated_triage`, so the new questions land in the object we
    #    return — the caller stays oblivious that generation happened here.
    old_top = {arm.name for arm in _qualifying_arms(current_triage)}
    new_top_arms = _qualifying_arms(updated_triage)
    newly_promoted = [
        arm
        for arm in new_top_arms
        if arm.name not in old_top and not arm.questions
    ]
    if newly_promoted:
        await asyncio.gather(
            *(
                ensure_arm_questions(arm, current_triage.chief_complaint, patient_context)
                for arm in newly_promoted
            )
        )

    return updated_triage, transitions
