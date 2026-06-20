"""Terminal runner for the full pipeline: triage -> questions -> answer -> re-score.

Sibling to `_run_triage.py` (which stays as the triage-only runner). This one runs the
whole feedback loop end to end in a single execution and prints the before/after of a
real re-score. No FastAPI route, no UI yet (CLAUDE.md Section 12). Run from backend/:

    PYTHONPATH=. uv run python app/agents/_run_pipeline.py

Edit the two constants below (or pass them as args) to try a different scenario.
"""

import asyncio
import sys
import time
from typing import cast

from pydantic import BaseModel

from app.config import QUESTION_GENERATION_THRESHOLD, QUESTION_GENERATOR_MODEL
from app.core.call_agent import call_agent
from app.core.orchestration import populate_questions
from app.core.rescore import process_answer
from app.models import ClinicalQuestion
from app.agents.triage import run_triage

# Same hardcoded chest-pain scenario as _run_triage.py, for a like-for-like compare.
# Optionally override from the command line to try another scenario without editing:
#   uv run python app/agents/_run_pipeline.py "chest pain" "35yo F, pleuritic pain"
CHIEF_COMPLAINT = "chest pain"
PATIENT_CONTEXT = (
    "62-year-old male, smoker, pain worse on exertion, radiates to left arm"
)
if len(sys.argv) >= 3:
    CHIEF_COMPLAINT, PATIENT_CONTEXT = sys.argv[1], sys.argv[2]


# --- Simulated patient answer (TEST SCAFFOLDING, not part of the agent pipeline) ----
#
# Step 3.4 of the build prompt: we don't hardcode an answer in advance — we pick a
# REAL generated question at runtime, then need a plausible answer to whatever it
# turned out to be. A tiny LLM call role-playing the patient is the cleanest way to
# get an answer that's actually consistent with the specific question and this patient
# (a deterministic "yes"/"no" couldn't stay coherent with an arbitrary question's
# intent). This lives in the runner, not the pipeline: in the real product the human
# clinician supplies this answer — this only stands in for that human during a
# headless demo. Routed to the cheap tier; it's a stand-in, not a safety-critical step.
class _SimulatedAnswer(BaseModel):
    answer_text: str


async def simulate_patient_answer(
    patient_context: str, question: ClinicalQuestion
) -> str:
    system_prompt = (
        "You are simulating a real patient answering a clinician's history-taking "
        "question during a consultation. Given the patient description and the exact "
        "question asked, reply in the patient's own voice with a brief, realistic "
        "answer (1-2 sentences). Stay consistent with the patient described; do not "
        "invent major new conditions, but it's fine to add small plausible detail."
    )
    user_prompt = (
        f"Patient: {patient_context}\n"
        f'Clinician asks: "{question.text}"\n'
        f"(The clinician is trying to establish: {question.diagnostic_intent})\n\n"
        f"Give the patient's brief answer."
    )
    result = await call_agent(
        model=QUESTION_GENERATOR_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=_SimulatedAnswer,
    )
    return cast(_SimulatedAnswer, result).answer_text


async def main() -> None:
    # 1 & 2. Triage, then generate questions concurrently.
    triage_output = await run_triage(CHIEF_COMPLAINT, PATIENT_CONTEXT)
    qualifying_count = sum(
        1
        for arm in triage_output.arms
        if arm.status == "active"
        and arm.relevance_score >= QUESTION_GENERATION_THRESHOLD
    )
    start = time.perf_counter()
    triage_output = await populate_questions(
        triage_output, CHIEF_COMPLAINT, PATIENT_CONTEXT
    )
    elapsed = time.perf_counter() - start

    print(f"Chief complaint: {triage_output.chief_complaint}")
    print(f"Patient: {PATIENT_CONTEXT}")
    print(
        f"Question generation: {qualifying_count} active arms, generated "
        f"concurrently in {elapsed:.2f}s\n"
    )
    print("=== INITIAL TRIAGE + QUESTIONS ===")
    for arm in sorted(triage_output.arms, key=lambda a: a.relevance_score, reverse=True):
        print(f"{arm.name:<28} {arm.relevance_score:>4.2f}   {arm.status}")
        print(f"  {arm.reasoning}")
        for question in arm.questions:
            print(f"    [{question.id}] {question.text}")
            print(f"        intent: {question.diagnostic_intent}")
        if not arm.questions:
            print("    (no questions)")
        print()

    # 3. Pick ONE real question to answer: the first question of the HIGHEST-scoring
    #    arm that actually has questions. Deterministic and clinically sensible (you'd
    #    pursue the most likely arm first), and it's a genuine pick from real output —
    #    nothing about this answer was decided before the run.
    arms_with_questions = [arm for arm in triage_output.arms if arm.questions]
    if not arms_with_questions:
        print("No arms produced questions — nothing to answer. Stopping.")
        return
    top_arm = max(arms_with_questions, key=lambda a: a.relevance_score)
    chosen_question = top_arm.questions[0]

    # 4. Construct a plausible answer to that specific question (see scaffolding note).
    answer_text = await simulate_patient_answer(PATIENT_CONTEXT, chosen_question)

    print("=== ANSWER RECORDED -> RE-SCORE TRIGGERED ===")
    print(f"Arm answered first: {top_arm.name} (score {top_arm.relevance_score:.2f})")
    print(f"Question [{chosen_question.id}]: {chosen_question.text}")
    print(f"Simulated patient answer: {answer_text}\n")

    # 5. Run the feedback loop.
    old_scores = {arm.name: arm.relevance_score for arm in triage_output.arms}
    old_reasoning = {arm.name: arm.reasoning for arm in triage_output.arms}
    updated_triage, transitions = await process_answer(
        chosen_question.id, answer_text, triage_output
    )

    # 6. Before/after for EVERY arm, with the new reasoning shown.
    print("=== BEFORE -> AFTER (every arm) ===")
    for arm in sorted(updated_triage.arms, key=lambda a: a.relevance_score, reverse=True):
        old = old_scores[arm.name]
        marker = " (changed)" if old != arm.relevance_score else ""
        print(f"{arm.name:<28} {old:>4.2f} -> {arm.relevance_score:<4.2f}{marker}")
        print(f"    old reasoning: {old_reasoning[arm.name]}")
        print(f"    new reasoning: {arm.reasoning}\n")

    # Explicitly print the ScoreTransition records (what the Trace Viewer will read).
    print("=== ScoreTransition records (changed arms only) ===")
    if not transitions:
        print("  (no arm scores changed)")
    for transition in transitions:
        delta = transition.new_score - transition.old_score
        print(
            f"  {transition.arm_name:<28} "
            f"{transition.old_score:.2f} -> {transition.new_score:.2f} "
            f"(delta {delta:+.2f})"
        )


if __name__ == "__main__":
    asyncio.run(main())
