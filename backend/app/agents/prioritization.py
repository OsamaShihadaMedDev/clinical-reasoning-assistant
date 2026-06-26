"""Prioritization Agent — re-scoring + red-flag safety, the third agent.

DELIBERATE DEVIATION FROM "ONE NARROW JOB PER AGENT" (CLAUDE.md Section 6, point 1):
Triage and Question Generator each do exactly one thing. This agent does TWO related
things in a single call — (1) re-score every arm in light of new evidence, and
(2) run a red-flag safety check over the resulting scores. This is a conscious scope
decision, not drift, and here is the justification: both judgments need the exact
same input — the full current picture of every arm's score and reasoning — and a
re-score that ignored red-flag risk would be incomplete on its own. The dangerous
failure mode this guards against (a can't-miss diagnosis silently sliding to the
bottom because likelihood dropped) is only visible while you hold the whole re-scored
set in view. Splitting it into two agents would mean a second full round-trip that
re-derives the same state purely to satisfy a pattern — exactly the "complexity for
its own sake" CLAUDE.md Section 11 says to reject. So: one call, two jobs, on purpose.

This is the agent behind the feedback loop CLAUDE.md calls the single most valuable
feature in the project (Section 5 step 5, Section 6 point 3): downstream state (the
user answering a question) re-triggers an upstream agent to REVISE its earlier output,
rather than the pipeline only ever flowing one way.

Routed to PRIORITIZATION_MODEL — the stronger/safety-critical tier (Section 7),
because this is the one place a wrong judgment can bury a life-threatening diagnosis.
"""

from typing import cast

from app.config import PRIORITIZATION_MODEL
from app.core.call_agent import call_agent
from app.models import RescoreTrigger, TriageOutput


def _find_answered_question_text(trigger: RescoreTrigger) -> str:
    """Recover the text of the question that was just answered, from the full arm
    state carried on the trigger. The trigger only stores the question *id*; giving
    the model the actual question text (not just "id X was answered") is what lets it
    reason about what the answer is responding to.
    """
    for arm in trigger.current_arms:
        for question in arm.questions:
            if question.id == trigger.question_id:
                return question.text
    # The orchestrator marks the question answered before building the trigger, so it
    # should always be present. If it isn't, fail loud rather than re-score against a
    # phantom answer with no context.
    raise ValueError(
        f"question_id '{trigger.question_id}' not found in the trigger's arm state — "
        f"cannot re-score against an answer whose question is unknown."
    )


def _build_system_prompt(red_flag_arm_names: set[str]) -> str:
    red_flags = ", ".join(sorted(red_flag_arm_names)) or "(none marked)"
    return f"""You are the Prioritization & Re-Scoring Agent in a clinical \
history-taking assistant. You assist history-taking; you do NOT diagnose, and the \
clinician remains the decision-maker.

The clinician has just recorded the patient's answer to one history-taking question. \
Your job has TWO parts, done together in this single pass:

1. RE-SCORE every diagnostic arm. Given the new answer, decide whether each arm has \
become MORE or LESS likely for THIS specific patient, and update BOTH its \
relevance_score (0 to 1) AND its reasoning together. The reasoning MUST reflect the \
NEW evidence — say what the answer told you and how that moved the score. Do NOT \
restate the old reasoning with a new number stapled on; a re-score that changes the \
number but not the explanation has not done its job. If the answer genuinely doesn't \
affect an arm, you may keep its score, but say briefly why it's unaffected.

2. RED-FLAG SAFETY CHECK. These arms are time-critical, can't-miss diagnoses: \
{red_flags}. relevance_score means LIKELIHOOD, not danger — do NOT inflate a \
red-flag arm's score just because it is dangerous. The score must stay an honest \
likelihood. Instead: if a red-flag arm's score is, or has just become, LOW, but the \
new answer does NOT actually rule it out, your reasoning for that arm MUST explicitly \
say it still cannot be excluded despite the low likelihood (call it a red flag). That \
honest reasoning is the safety net — never a rigged number.

INTERPRETING AMBIGUOUS OR COLLOQUIAL PATIENT LANGUAGE. Patients often describe \
symptoms in informal, vague, or non-standard words rather than textbook clinical \
descriptors. Do NOT treat unfamiliar phrasing as evidence of atypicality — the reflex \
"this isn't a classic descriptor, therefore it lowers the likelihood" is a known error \
and you must resist it. Instead, FIRST consider the most clinically plausible \
interpretation(s) of what the patient likely means, and reason from that, not from the \
strangeness of the words. Then keep two genuinely different conclusions separate \
rather than collapsing them into one "unfamiliar -> atypical -> lower" reflex: \
(a) once interpreted plausibly, the answer points TOWARD or AWAY from an arm — move \
the score in that direction; versus (b) the wording is truly ambiguous and supports no \
confident reading either way — here do NOT silently pick a direction. Say so in the \
reasoning (e.g. "the patient's description is non-specific; cannot confidently move \
the score on this answer alone") and leave the score where it is. This is the same \
honesty principle as the red-flag check above: surface the uncertainty rather than \
papering over it with a confident number.

Hard rules:
- Return EVERY arm you are given, each with its EXACT same name. Do not invent, \
rename, merge, or drop any arm.
- relevance_score must be between 0 and 1.
- status: echo each arm's status exactly as given — you do not change it.
- questions: set questions to an EMPTY LIST ([]) for every arm. You are NOT \
generating or editing questions; the system preserves the real questions separately. \
This is a hard requirement: questions must be [] for all arms.
- chief_complaint: echo the complaint you are given."""


async def rescore_arms(
    trigger: RescoreTrigger,
    chief_complaint: str,
    red_flag_arm_names: set[str],
) -> TriageOutput:
    """Re-score every arm in light of one new answer, and apply the red-flag check.

    Returns a `TriageOutput` — the SAME contract shape as initial triage, because a
    re-score is the same kind of object (a snapshot of current arm state), just
    revised. No new output type is invented for this.

    The model is asked only to revise scores + reasoning (and to emit empty question
    lists). We then merge those revisions back onto the arms the trigger carried,
    keeping each arm's real questions, status, and answered state intact. The model is
    deliberately NOT trusted to faithfully re-emit the questions (ids, the answered
    flag, exact text) — preserving them in code is both safer and cheaper, and mirrors
    how the orchestrator computes ScoreTransitions in code rather than asking the
    model to self-report what changed.
    """
    answered_text = _find_answered_question_text(trigger)

    arm_lines = "\n".join(
        f"- {arm.name} | current score {arm.relevance_score:.2f} | {arm.reasoning}"
        for arm in trigger.current_arms
    )
    system_prompt = _build_system_prompt(red_flag_arm_names)
    user_prompt = (
        f"Chief complaint: {chief_complaint}\n\n"
        f"The patient has just answered this question:\n"
        f'  Question: "{answered_text}"\n'
        f'  Answer:   "{trigger.answer_text}"\n\n'
        f"Current state of every diagnostic arm:\n{arm_lines}\n\n"
        f"Re-score every arm in light of this new answer, update each arm's reasoning "
        f"to reflect it, and apply the red-flag safety check."
    )

    result = await call_agent(
        model=PRIORITIZATION_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=TriageOutput,
    )
    revised = cast(TriageOutput, result)

    # Merge the model's revised score+reasoning back onto the arms we already hold,
    # matching by name. Iterating the CURRENT arms (not the model's) is what makes
    # this robust: an arm the model accidentally dropped or renamed simply keeps its
    # prior values instead of vanishing, and questions/status/answered are always
    # carried over from the real state, never from the model's output.
    revised_by_name = {arm.name: arm for arm in revised.arms}
    merged_arms = []
    for current_arm in trigger.current_arms:
        revision = revised_by_name.get(current_arm.name)
        if revision is not None:
            merged_arms.append(
                current_arm.model_copy(
                    update={
                        "relevance_score": revision.relevance_score,
                        "reasoning": revision.reasoning,
                    }
                )
            )
        else:
            merged_arms.append(current_arm)

    # chief_complaint comes from our caller, not the model — authoritative in code.
    return TriageOutput(chief_complaint=chief_complaint, arms=merged_arms)
