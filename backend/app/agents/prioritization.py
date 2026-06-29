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
from app.models import HistoryAnswer, RescoreTrigger, TriageOutput


def _build_system_prompt(
    red_flag_arm_names: set[str], newly_added_arm_names: set[str]
) -> str:
    red_flags = ", ".join(sorted(red_flag_arm_names)) or "(none marked)"

    # Only included when this re-score was triggered by the clinician ADDING arms (the
    # /api/arm/custom path), following the same conditional-context style as the general-
    # history block in rescore_arms. Empty string for the ordinary answer-driven re-score,
    # so that path's prompt is unchanged.
    newly_added_block = ""
    if newly_added_arm_names:
        added = ", ".join(sorted(newly_added_arm_names))
        newly_added_block = f"""

NEWLY ADDED ARMS. The clinician has just added these arms to the differential because \
they suspected something the initial framework may have missed: {added}. These arms have \
NO answered questions of their own yet and arrive carrying a PLACEHOLDER score you MUST \
replace with a real one. Score each newly added arm honestly against everything already \
known about THIS specific case — the chief complaint, the patient context, the general \
history answers, and the evidence already gathered for the other arms where it overlaps — \
exactly as you would an arm discovered at triage. Do NOT leave a newly added arm at a \
default/middling score just because it is new, and do NOT inflate it just because the \
clinician raised it. Because every arm (new and existing) is scored together in this one \
pass, weigh the new arms against and alongside the existing differential, not in \
isolation, and let them shift the existing arms' scores where that is warranted."""

    return f"""You are the Prioritization & Re-Scoring Agent in a clinical \
history-taking assistant. You assist history-taking; you do NOT diagnose, and the \
clinician remains the decision-maker.

The clinician has just recorded the patient's answer(s) to one or more history-taking \
questions, all from the same card, submitted together. \
Your job has TWO parts, done together in this single pass:

1. RE-SCORE every diagnostic arm. Given the new answer(s), decide whether each arm has \
become MORE or LESS likely for THIS specific patient, and update BOTH its \
relevance_score (0 to 1) AND its reasoning together. Consider ALL of the new answers \
TOGETHER when re-scoring each arm — they were collected as one batch and may interact \
(e.g. two answers together may move a score further, or in a different direction, than \
either one alone would). The reasoning MUST reflect the NEW evidence — say what the \
answer(s) told you and how that moved the score. Do NOT restate the old reasoning with \
a new number stapled on; a re-score that changes the number but not the explanation has \
not done its job. If the new answers genuinely don't affect an arm, you may keep its \
score, but say briefly why it's unaffected.

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

GENERAL PATIENT HISTORY CONTEXT. Alongside the just-answered question, you may also be \
given a list of the patient's GENERAL history answers gathered for this interview \
(past medical history, medications, allergies, smoking/alcohol/substance use, family \
history, baseline function). These are background facts about the patient, NOT scored \
items and NOT tied to any one arm. Use them as additional context that can legitimately \
raise or lower an arm's likelihood — e.g. a heavy smoking history raises cardiac, \
vascular, and respiratory arms; an anticoagulant or bleeding history raises haemorrhagic \
arms. When such a fact is relevant to an arm you move, say so in that arm's reasoning. \
When the trigger for this re-score is itself a general-history answer, treat it the same \
way: revise the arms whose likelihood that background fact changes.{newly_added_block}

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
    history_answers: list[HistoryAnswer],
) -> TriageOutput:
    """Re-score every arm in light of a BATCH of new answers, and apply the red-flag
    check.

    Returns a `TriageOutput` — the SAME contract shape as initial triage, because a
    re-score is the same kind of object (a snapshot of current arm state), just
    revised. No new output type is invented for this.

    The just-answered questions come from `trigger.new_answers`, each of which already
    carries its own `question_text` (resolved upstream by the caller, which is the one
    place that can resolve text for BOTH arm questions and general-history questions —
    the latter don't live in `current_arms`). So this function does NOT re-resolve text
    from the arm state; it renders the batch directly. A single-answer submit is just a
    one-element batch.

    `history_answers` is the full set of general-history answers collected so far this
    session (possibly empty). It is rendered as plain question/answer context so the
    Prioritization Agent can weigh patient background — the SAME single agent call,
    just with one extra context block (one loop, not two pipelines).

    The model is asked only to revise scores + reasoning (and to emit empty question
    lists). We then merge those revisions back onto the arms the trigger carried,
    keeping each arm's real questions, status, and answered state intact. The model is
    deliberately NOT trusted to faithfully re-emit the questions (ids, the answered
    flag, exact text) — preserving them in code is both safer and cheaper, and mirrors
    how the orchestrator computes ScoreTransitions in code rather than asking the
    model to self-report what changed.
    """
    arm_lines = "\n".join(
        f"- {arm.name} | current score {arm.relevance_score:.2f} | {arm.reasoning}"
        for arm in trigger.current_arms
    )

    # The batch of newly-answered questions, one line each. Plural by design: a
    # card-level submit can carry several, and the prompt asks the model to weigh them
    # jointly. A one-element batch renders as a single line — identical in spirit to the
    # old single-answer block. May be EMPTY when the re-score was triggered by added arms
    # rather than new answers (the event block below switches framing in that case).
    qa_lines = "\n".join(
        f'  - Question: "{a.question_text}"  ->  Answer: "{a.answer_text}"'
        for a in trigger.new_answers
    )

    # What kicked off this re-score: new answers (the usual case) OR newly added arms with
    # no accompanying answers (the /api/arm/custom path). Keep the answer-driven wording
    # byte-for-byte unchanged so that verified behavior is untouched; only the
    # no-answers/added-arms case gets the alternate framing.
    if trigger.new_answers:
        event_block = (
            "The clinician has just recorded these answer(s), submitted together:\n"
            f"{qa_lines}\n\n"
        )
        instruction = (
            "Re-score every arm in light of these new answers TOGETHER (and the general "
            "history above, if any), update each arm's reasoning to reflect them, and "
            "apply the red-flag safety check."
        )
    else:
        added = ", ".join(trigger.newly_added_arm_names)
        event_block = (
            f"The clinician has just ADDED these arms to the differential: {added}. "
            "No new patient answers accompany this change.\n\n"
        )
        instruction = (
            "Re-score every arm — including the newly added ones — TOGETHER, accounting "
            "for each other and everything already known (chief complaint, patient "
            "context, general history). Replace each newly added arm's placeholder score "
            "and reasoning with a real, case-specific one, and apply the red-flag safety "
            "check."
        )

    # Render the general-history context block only when there ARE history answers, so
    # an arm-triggered re-score with no history yet produces a prompt close to the
    # pre-history behavior (keeping the verified arm-only behavior unchanged).
    history_block = ""
    if history_answers:
        history_lines = "\n".join(
            f'  - Q: "{h.question_text}"  A: "{h.answer_text}"'
            for h in history_answers
        )
        history_block = (
            f"General history collected for this patient so far:\n{history_lines}\n\n"
        )

    system_prompt = _build_system_prompt(
        red_flag_arm_names, set(trigger.newly_added_arm_names)
    )
    user_prompt = (
        f"Chief complaint: {chief_complaint}\n\n"
        f"{event_block}"
        f"{history_block}"
        f"Current state of every diagnostic arm:\n{arm_lines}\n\n"
        f"{instruction}"
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
