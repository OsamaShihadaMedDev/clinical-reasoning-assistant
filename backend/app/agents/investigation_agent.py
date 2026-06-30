"""Investigation Suggestion Agent — on-demand "what would you order right now".

WHY THIS IS AN AGENT, NOT A TEMPLATE (the justification for spending an LLM call here):
a fixed per-complaint workup template ("chest pain -> ECG, troponin, CXR") would need no
model. The real decision is case-specific: which baseline tests fit THIS patient, and —
for the top-scoring arms only — which single test would most directly rule each one in or
out given this patient's risk factors and answers so far, with red-flag arms weighted
toward defensible exclusion even at a modest score. That is selection-and-justification
over the whole case state, the same kind of judgment suggestion_agent.py makes, so it
gets its own small agent routed cheap/fast (INVESTIGATION_MODEL): the hard diagnostic
reasoning already happened upstream in Prioritization; this is a read-and-suggest.

Scope is narrow (CLAUDE.md Section 6): this agent suggests tests/imaging to CONSIDER and
writes a one-line reason for each. It does NOT diagnose, order tests, re-score arms, or
mutate any session state — it is a pure read+suggest snapshot (see /api/investigations).

Don't-trust-the-model discipline (same as _merge_suggestions): everything identity-
bearing is recomputed/validated in code after the call (`_merge_investigations`) — a
specialized item naming an arm outside the top-N set passed in is dropped, every routine
item's arm_name is forced to None, and a test duplicated across both tiers is collapsed
to its specialized occurrence. The model only chooses WHICH tests, in which tier, with
what reasoning.
"""

import logging
from typing import cast

from app.config import INVESTIGATION_MODEL
from app.core.call_agent import call_agent
from app.core.orchestration import _top_investigation_arms
from app.models import (
    DiagnosticArm,
    HistoryAnswer,
    InvestigationBatch,
    InvestigationSuggestion,
    TriageOutput,
)

logger = logging.getLogger(__name__)


def _build_system_prompt(red_flag_arm_names: set[str]) -> str:
    red_flags = ", ".join(sorted(red_flag_arm_names)) or "(none marked)"

    return f"""You are the Investigation Suggestion Agent in a clinical \
history-taking assistant. You assist the clinician's workup planning; you do NOT \
diagnose, order tests, or make treatment decisions — the clinician remains the \
decision-maker and may act on, modify, or ignore anything you suggest.

The clinician has asked, at this point in the interview, what tests and imaging might \
be worth considering given everything gathered so far. Your job has TWO separate parts:

1. ROUTINE WORKUP. Baseline labs/testing appropriate for THIS chief complaint and \
patient context REGARDLESS of which specific diagnosis turns out to be correct.
2. SPECIALIZED WORKUP. You will be given the TOP-SCORING diagnostic arms only \
(already selected for you). For each one, suggest the test(s)/imaging that would most \
directly RULE IN or RULE OUT that specific diagnosis for this patient.

RED-FLAG AWARENESS. These arms are time-critical, can't-miss diagnoses: {red_flags}. \
If a red-flag arm appears among the top-scoring arms you were given, even at a modest \
score, weigh its specialized suggestion toward tests that would defensibly exclude it, \
not just toward whichever test best confirms the highest-scoring arm overall.

REASONING LENGTH. Each suggestion gets exactly ONE short sentence of reasoning — this \
is a glance-able list for a clinician already mid-case, not a report. State the \
clinical reason plainly and stop.

Below are worked examples showing the EXACT distinction you must hold. Study what \
makes the GOOD output correct and the BAD output wrong — these are not style \
preferences, they are the rules above made concrete.

---
EXAMPLE 1 — keeping Routine arm-free

CASE: Chief complaint "chest pain," top arms: Cardiac (ACS) 0.71, Pulmonary Embolism \
0.52.

GOOD routine item:
  name: "ECG"
  reasoning: "Baseline assessment for any patient presenting with chest pain."
  -> Correct because the reasoning justifies itself from the CHIEF COMPLAINT alone. \
A clinician would order this before any arm separated from the pack.

BAD routine item (do NOT produce this):
  name: "ECG"
  reasoning: "Useful given the elevated likelihood of ACS in this differential."
  -> Wrong because it leans on one arm's score. The moment a routine item's reasoning \
needs an arm name or that arm's likelihood to make sense, it has secretly become a \
Specialized item and must be moved there instead, tied to that arm.

---
EXAMPLE 2 — every Specialized item needs a real arm behind it

GOOD specialized item:
  name: "CT pulmonary angiography"
  arm_name: "Pulmonary Embolism"
  reasoning: "Most direct way to confirm or exclude PE given its current likelihood."
  -> Correct: names the arm, the test is chosen FOR that arm specifically, and it \
would not appear in the suggestion set at all if that arm weren't in the top-scoring \
list you were given.

BAD specialized item (do NOT produce this):
  name: "Basic metabolic panel"
  arm_name: "Pulmonary Embolism"
  reasoning: "Generally useful for assessing overall patient status."
  -> Wrong twice over: a BMP doesn't actually rule PE in or out (the test doesn't \
match the arm it's claimed to serve), AND the reasoning given is a routine-style \
justification wearing a Specialized label. If a test is justifiable on case-general \
grounds, it belongs in Routine, not stapled onto an arm it doesn't actually test.

---
EXAMPLE 3 — no duplicate item across tiers

CASE: Chief complaint "shortness of breath," top arm includes Pulmonary Embolism 0.66.

GOOD: "D-dimer" appears ONCE, under Specialized, tied to Pulmonary Embolism, with \
reasoning referencing that arm. It does NOT also appear under Routine.

BAD (do NOT produce this): "D-dimer" listed under BOTH Routine (reasoning: "commonly \
checked in dyspnea workups") AND Specialized for Pulmonary Embolism. \
-> Wrong because the same test is being justified twice with two different stories. \
If a test could plausibly belong in either tier, the MORE SPECIFIC justification wins \
— here that's Specialized — and it must be removed from the other tier entirely.

---
EXAMPLE 4 — reasoning length discipline

GOOD: "D-dimer" — reasoning: "Sensitive screen for PE; appropriate given its current \
likelihood in this differential."

BAD (do NOT produce this): "D-dimer" — reasoning: "D-dimer is a sensitive but \
non-specific test that can help rule out venous thromboembolism, and while an elevated \
result does not confirm PE, in the context of this patient's presentation and given \
the moderate pre-test probability suggested by the current differential, it would be \
a reasonable next step before proceeding to more specific imaging."
-> Wrong because it is a paragraph, not a sentence. A clinician scanning this list \
needs the reason in one breath, not a teaching explanation.

---

Now produce Routine and Specialized suggestions for the actual case below, following \
exactly the distinctions shown above. Do not repeat the example cases' content — they \
are pattern references only, not part of this patient's case.
"""


def _build_user_prompt(
    chief_complaint: str,
    patient_context: str,
    top_arms: list[DiagnosticArm],
    answered: list[tuple[str, str]],
) -> str:
    """Assemble the case-so-far for the model. Only the TOP-N arms are handed in (not the
    whole differential) — same scoping discipline as `ensure_arm_questions` callers never
    handing the model arms outside their intended scope; Specialized suggestions can only
    legitimately attach to an arm the model was actually shown."""
    arm_lines = "\n".join(
        f"- {arm.name} | score {arm.relevance_score:.2f} | {arm.reasoning}"
        for arm in top_arms
    )

    if answered:
        answered_lines = "\n".join(
            f'- "{question_text}" -> "{answer_text}"'
            for question_text, answer_text in answered
        )
    else:
        answered_lines = "(no questions answered yet)"

    return (
        f"Chief complaint: {chief_complaint}\n\n"
        f"Patient context: {patient_context or '(none provided)'}\n\n"
        f"Top-scoring diagnostic arms (Specialized suggestions may ONLY be tied to one "
        f"of these — use the EXACT arm name shown):\n{arm_lines}\n\n"
        f"Questions answered so far (history-taking + general history):\n"
        f"{answered_lines}\n\n"
        f"Produce the Routine and Specialized workup suggestions for this case."
    )


def _merge_investigations(
    raw: InvestigationBatch,
    valid_arm_names: set[str],
    total_answered_count: int,
) -> InvestigationBatch:
    """Pure, deterministic validation of the model's raw output (NO AI call).

    Trust the model only for WHICH tests, in which tier, with what reasoning. Everything
    identity-bearing is enforced in code, mirroring `_merge_suggestions`:
      - ROUTINE: force every item's arm_name to None regardless of what the model set
        (a routine item is by definition not tied to an arm).
      - SPECIALIZED: drop any item whose arm_name is not literally one of the top-N arm
        names passed in (an invented or out-of-scope arm — same discipline
        SuggestedQuestion.source_arms gets). An item with arm_name None is also dropped:
        a specialized suggestion with no arm behind it is exactly EXAMPLE 2's failure.
      - CROSS-TIER DEDUP: if a test name appears in BOTH tiers (case-insensitive), keep
        the SPECIALIZED occurrence and drop the routine one — code enforcement of
        EXAMPLE 3, not reliance on the prompt alone.
      - stamp `generated_at_answer_count` from the authoritative count computed in code,
        never the model's echo.
    Kept as a standalone pure function precisely so it can be unit-tested without an LLM
    call (the prompt flags it as a test candidate, alongside _top_investigation_arms).
    """
    specialized: list[InvestigationSuggestion] = []
    for item in raw.specialized:
        if item.arm_name is None or item.arm_name not in valid_arm_names:
            logger.warning(
                "Investigation Agent gave a specialized item %r with invalid arm_name "
                "%r; dropping.",
                item.name,
                item.arm_name,
            )
            continue
        specialized.append(item)

    # Names already claimed by Specialized win the cross-tier tie (EXAMPLE 3).
    specialized_names = {item.name.strip().lower() for item in specialized}

    routine: list[InvestigationSuggestion] = []
    for item in raw.routine:
        if item.name.strip().lower() in specialized_names:
            logger.warning(
                "Investigation Agent listed %r in BOTH tiers; keeping the specialized "
                "occurrence and dropping the routine one.",
                item.name,
            )
            continue
        # A routine item is never tied to an arm — force it regardless of the model.
        routine.append(
            InvestigationSuggestion(
                name=item.name,
                reasoning=item.reasoning,
                arm_name=None,
            )
        )

    return InvestigationBatch(
        routine=routine,
        specialized=specialized,
        generated_at_answer_count=total_answered_count,
    )


async def suggest_investigations(
    triage_output: TriageOutput,
    patient_context: str,
    history_answers: list[HistoryAnswer],
    red_flag_arm_names: set[str],
    total_answered_count: int,
) -> InvestigationBatch:
    """Suggest routine + specialized workup for the case as it stands right now.

    A snapshot, not a loop step: it reads the current interview state (top arms, patient
    context, every answer so far) and returns one batch of suggestions. The top-N arm
    selection is delegated to `orchestration._top_investigation_arms` (NOT reimplemented
    here) so the active-then-rank rule lives in one place; only those arms are shown to
    the model. `total_answered_count` is computed by the caller (the route) and carried
    straight through onto the batch for the frontend's staleness marker.
    """
    top_arms = _top_investigation_arms(triage_output)

    # Every answer so far, from BOTH sources, resolved the same way `_apply_answers`
    # already records them — arm answers carry their text+answer on the question, history
    # answers carry theirs on the HistoryAnswer. No second id-resolution path.
    answered: list[tuple[str, str]] = []
    for arm in triage_output.arms:
        for question in arm.questions:
            if question.answered and question.answer_text is not None:
                answered.append((question.text, question.answer_text))
    for history_answer in history_answers:
        answered.append((history_answer.question_text, history_answer.answer_text))

    system_prompt = _build_system_prompt(red_flag_arm_names)
    user_prompt = _build_user_prompt(
        triage_output.chief_complaint, patient_context, top_arms, answered
    )

    raw = cast(
        InvestigationBatch,
        await call_agent(
            model=INVESTIGATION_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=InvestigationBatch,
        ),
    )

    valid_arm_names = {arm.name for arm in top_arms}
    return _merge_investigations(raw, valid_arm_names, total_answered_count)
