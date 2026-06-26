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
    ClinicalQuestion,
    Framework,
    RescoreTrigger,
    ScoreTransition,
    TriageOutput,
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
    """Locate a question by id across ALL arms. Ids are globally unique (namespaced
    per arm by the Question Generator), so the first match is the only match."""
    for arm in triage.arms:
        for question in arm.questions:
            if question.id == question_id:
                return question
    return None


async def process_answer(
    question_id: str,
    answer_text: str,
    current_triage: TriageOutput,
    patient_context: str,
    framework: Framework,
) -> tuple[TriageOutput, list[ScoreTransition]]:
    """Apply one answered question to the interview and re-score the arms.

    Returns the updated `TriageOutput` AND the list of `ScoreTransition` records for
    arms whose score actually moved. The caller (the /api/answer route / Trace Viewer)
    needs both: the new state to render, and the transitions to show WHY it changed.

    `patient_context` is threaded through because a re-score can change WHICH arms are
    in the auto-generated top N: if this answer lifts a previously-quiet arm into the
    top N, we generate its questions here (using the same patient context the initial
    fan-out used, so lazily-generated arms are tailored identically) so the caller gets
    one fully-consistent state and never has to know lazy generation happened.

    `framework` is this session's resolved diagnostic-arm framework. We derive the
    red-flag (can't-miss) arm names from it here, per session, rather than from a
    module-level constant — see the DATA-SOURCE CHANGE note at the top of this file.
    `DiagnosticArm` (what `current_triage` carries) deliberately does NOT carry
    red_flag, so the framework is the only place this information lives.
    """
    # Per-session red-flag set: the time-critical arms the Prioritization Agent's
    # safety check must never let silently sink. Derived from THIS session's framework.
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}

    # 1. Mark the answered question on the current state. This mutates the existing
    #    ClinicalQuestion in place, so the answered flag/text travel with the arm into
    #    the trigger below (and survive the re-score, which preserves questions).
    question = _find_question(current_triage, question_id)
    if question is None:
        raise ValueError(
            f"question_id '{question_id}' not found in the current triage state."
        )
    question.answered = True
    question.answer_text = answer_text

    # 2. Build the feedback-loop input. RescoreTrigger carries the FULL current arm
    #    state, not just the new answer — re-scoring is a revision of prior scores,
    #    not a fresh calculation, so the agent must see what it's revising.
    trigger = RescoreTrigger(
        question_id=question_id,
        answer_text=answer_text,
        current_arms=current_triage.arms,
    )

    # 3. Re-score (the actual agent call).
    updated_triage = await rescore_arms(
        trigger,
        chief_complaint=current_triage.chief_complaint,
        red_flag_arm_names=red_flag_arm_names,
    )

    # 4. Compute ScoreTransitions IN CODE by diffing old vs new scores per arm name —
    #    never trust the model to self-report what changed, since the delta is a fact
    #    we can compute directly and verify. Only emit a transition for arms that
    #    actually moved, so the trace isn't padded with zero-delta noise.
    old_scores = {arm.name: arm.relevance_score for arm in current_triage.arms}
    transitions = [
        ScoreTransition(
            arm_name=arm.name,
            old_score=old_scores[arm.name],
            new_score=arm.relevance_score,
            trigger_answer=answer_text,
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
