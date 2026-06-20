"""Question Generator Agent — the second agent in the project.

Its scope is deliberately narrow (CLAUDE.md Section 6, point 1): given ONE already-
scored diagnostic arm and a description of the specific patient, it writes a focused
set of history-taking questions for THAT arm. It does NOT score arms, rank them, or
decide which arms deserve questions — that is the Triage Agent's job (upstream) and
the orchestrator's job (which arms qualify). Keeping that boundary sharp is part of
what makes the "multi-agent" claim honest rather than one prompt wearing many hats.

Every question carries a `diagnostic_intent` (CLAUDE.md Section 3): what it rules in
or out for THIS arm specifically — the product's core insight that the clinician
understands *why* they're asking, not just *what* to ask.
"""

import re
from typing import cast

from pydantic import BaseModel

from app.config import QUESTION_GENERATOR_MODEL
from app.core.call_agent import call_agent
from app.models import ClinicalQuestion, DiagnosticArm


class QuestionList(BaseModel):
    """Transport-only wrapper for this agent's response shape.

    `call_agent()` constrains output to a single Pydantic model, but this agent
    conceptually returns a *list* of questions. JSON Schema can't have a bare array
    as the top-level structured-output object, so we wrap the list in a one-field
    model purely so `call_agent()` has a `BaseModel` to validate against. It is
    unwrapped immediately in `generate_questions()` — callers only ever see a plain
    `list[ClinicalQuestion]`.

    Deliberately NOT exported from `app.models`: that package holds inter-agent
    handoff *contracts*, and this is not one — it's an internal response envelope
    that never crosses an agent boundary. Flagged as a new (narrow) addition in the
    build report.
    """

    questions: list[ClinicalQuestion]


def _slugify(name: str) -> str:
    """Turn an arm name into a stable, URL-safe id stem, e.g.
    "Cardiac (ACS / Ischemic)" -> "cardiac-acs-ischemic".

    Used to namespace question ids per arm (see `generate_questions`).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "arm"


def _build_system_prompt(arm: DiagnosticArm) -> str:
    return f"""You are the Question Generator Agent in a clinical history-taking \
assistant. You assist history-taking; you do NOT diagnose, and the clinician \
remains the decision-maker.

Your scope is narrow and you must stay inside it: you are given ONE diagnostic arm \
that another agent has already scored as relevant for this patient, and you write \
the history-taking questions for THAT arm only. You do NOT score the arm, you do \
NOT compare it to other arms, and you do NOT invent other arms. Just write good \
questions for the arm below.

The diagnostic arm you are writing questions for:
- Arm: {arm.name}
- Why it was scored relevant for this patient: {arm.reasoning}

Generate 3 to 5 focused history-taking questions a clinician would ask THIS patient \
to investigate THIS arm. Requirements for each question:
- It must be a question the clinician asks the PATIENT during history-taking \
(symptoms, timing, risk factors, associated features) — not an examination finding, \
investigation, or instruction.
- It must be specific to this arm and, where the patient details allow, tailored to \
this patient — not a generic catch-all history question.
- diagnostic_intent: state what answering it would rule IN or rule OUT for THIS arm \
specifically (e.g. "Pleuritic, worse on inspiration → raises pulmonary embolism / \
pneumothorax, lowers cardiac ischemia"). This is the point of the question — make it \
concrete, not a restatement of the question text.

For every question also set:
- id: the question's position as a string ("1", "2", ...). These are normalized to \
globally-unique ids after you respond, so don't overthink them.
- answered: false
- answer_text: null

Ground the questions in standard clinical reasoning for this arm. Do not fabricate \
exotic or unsafe content; this is a generalist, teaching-level assistant."""


async def generate_questions(
    arm: DiagnosticArm,
    chief_complaint: str,
    patient_context: str,
) -> list[ClinicalQuestion]:
    """Generate intent-labeled history-taking questions for ONE diagnostic arm.

    This function knows nothing about the other arms — it operates on a single arm
    in isolation (CLAUDE.md Section 6, point 1). That isolation is exactly what lets
    the orchestrator fan many of these out concurrently (see `orchestration.py`).
    """
    system_prompt = _build_system_prompt(arm)
    user_prompt = (
        f"Chief complaint: {chief_complaint}\n"
        f"Patient: {patient_context}\n"
        f"Diagnostic arm to investigate: {arm.name}\n\n"
        f"Write the history-taking questions for this arm."
    )

    result = await call_agent(
        model=QUESTION_GENERATOR_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=QuestionList,
    )

    # call_agent is generic over BaseModel; the validated instance is concretely a
    # QuestionList here, so we narrow the type, then unwrap to the plain list the
    # rest of the pipeline expects.
    questions = cast(QuestionList, result).questions

    # Reassign authoritative ids in code rather than trusting the model's. The id
    # must be unique across the WHOLE interview (RescoreTrigger.question_id matches a
    # question by id across every arm — see clinical.py), but this function only sees
    # one arm and can't guarantee global uniqueness on its own. Namespacing each id
    # with the arm's slug solves it: arm names are unique within a TriageOutput (the
    # Triage Agent is forbidden from renaming/dropping arms), so "cardiac-acs-...-1"
    # can never collide with "pulmonary-embolism-1". Done here, where the arm name is
    # known, so the orchestrator doesn't need to re-walk and renumber.
    slug = _slugify(arm.name)
    return [
        question.model_copy(update={"id": f"{slug}-{index}"})
        for index, question in enumerate(questions, start=1)
    ]
