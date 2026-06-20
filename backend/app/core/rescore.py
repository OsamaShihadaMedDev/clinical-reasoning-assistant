"""Re-scoring orchestration — the feedback loop's glue.

This closes the loop CLAUDE.md Section 5 step 5 / Section 6 point 3 describe: the user
checking off an answer doesn't just update a flag, it re-triggers the Prioritization
Agent to REVISE the earlier triage scores. This module is what turns a single answer
into (a) an updated interview state and (b) the ScoreTransition records the Trace
Viewer (Section 6b) will later render — the visible proof the loop did something.
"""

from app.agents.frameworks.chest_pain import CHEST_PAIN_ARMS
from app.agents.prioritization import rescore_arms
from app.models import ClinicalQuestion, RescoreTrigger, ScoreTransition, TriageOutput

# Which arms are the time-critical, can't-miss ones. Derived from the framework's
# red_flag markers (until now recorded but unused by any agent — this is the first
# consumer). Single-complaint MVP, so the chest pain framework is wired in directly;
# this is the exact seam where a multi-complaint version would later select the right
# framework by chief_complaint instead of importing one.
_RED_FLAG_ARM_NAMES = {arm.name for arm in CHEST_PAIN_ARMS if arm.red_flag}


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
) -> tuple[TriageOutput, list[ScoreTransition]]:
    """Apply one answered question to the interview and re-score the arms.

    Returns the updated `TriageOutput` AND the list of `ScoreTransition` records for
    arms whose score actually moved. The caller (a future SSE endpoint / Trace Viewer)
    needs both: the new state to render, and the transitions to show WHY it changed.
    """
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
        red_flag_arm_names=_RED_FLAG_ARM_NAMES,
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

    return updated_triage, transitions
