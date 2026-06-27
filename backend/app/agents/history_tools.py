"""History tools — the actions the History Agent's loop (history_agent.py) takes.
Mirrors framework_tools.py in spirit: each function is one tool, the docstrings are
the interface the agent reasons against, and only the generation/classification tools
call an LLM (always through the one shared call_agent()).

Three tools:
  - classify_patient_category — which population is this patient? (cheap/fast)
  - generate_checklist        — draft a population's general-history checklist (strong)
  - save_checklist            — persist a generated checklist to the cache

DELIBERATE DEVIATION FROM THE SPEC'S 2-TUPLE SIGNATURE (flagged, not silent):
the build prompt sketches `classify_patient_category -> tuple[PatientCategory, str]`,
but this implementation returns a 3-tuple `(category, reasoning, assumed_default)`.
Reason: `assumed_default` ("did we have to GUESS the category, or was it
context-supported?") is a fact only the classifier knows — Step 6 needs it, and the
clean way to get it is to return it from where it's decided, rather than have the
agent re-derive "was this a fallback?" heuristically after the fact. The enum and the
HistoryChecklist shape are unchanged; only this internal tuple carries one extra bool.
"""

from typing import cast

from pydantic import BaseModel

from app.config import HISTORY_CLASSIFICATION_MODEL, HISTORY_GENERATION_MODEL
from app.core import history_store
from app.core.call_agent import call_agent
from app.models import (
    HISTORY_QUESTION_ID_PREFIX,
    HistoryQuestion,
    PatientCategory,
)


class _CategoryClassification(BaseModel):
    """Response contract for the classification call. `assumed_default` is the
    model's own signal that it lacked enough population information and fell back to
    adult_general (vs choosing adult_general confidently from real context)."""

    category: PatientCategory
    reasoning: str
    assumed_default: bool


class _ChecklistDraft(BaseModel):
    """Transport-only wrapper for the generation response — same pattern as the
    Question Generator's QuestionList: call_agent constrains output to ONE model, and
    JSON Schema can't return a bare top-level array, so we wrap the list and unwrap it
    immediately. Not an inter-agent contract, so it lives here, not in app.models."""

    questions: list[HistoryQuestion]


async def classify_patient_category(
    patient_context: str,
) -> tuple[PatientCategory, str, bool]:
    """Classify the patient into one PatientCategory from the free-text
    patient_context ALONE, returning (category, reasoning, assumed_default).

    Hard rule (Step 4): if patient_context is empty, whitespace-only, or carries no
    population-bearing information (no age, sex, pregnancy status, surgical history, or
    pediatric/geriatric indicators), this returns ADULT_GENERAL with assumed_default=
    True and a reasoning string that plainly says why. We do NOT let the model guess a
    narrower category from chief-complaint wording — chief complaint is a poor, risky
    population signal ("leg pain" fits almost any category), and inventing age/sex that
    was never stated is exactly the unstated-assumption risk this design avoids.

    Routed to HISTORY_CLASSIFICATION_MODEL (cheap/fast) — frequent, low-stakes, same
    tier as FRAMEWORK_MATCH_MODEL.
    """
    # Deterministic short-circuit for genuinely empty context: no LLM call needed, and
    # it guarantees the mandated default behavior for the most common thin-input case.
    if not patient_context.strip():
        return (
            PatientCategory.ADULT_GENERAL,
            "No patient context was provided, so the general adult checklist is shown "
            "by default. Add age, sex, or other details and re-run for a more specific "
            "one.",
            True,
        )

    allowed = ", ".join(c.value for c in PatientCategory)
    system_prompt = f"""You are the population-classification step of a clinical \
history-taking assistant. From the patient description ALONE, classify the patient \
into exactly one of these population categories: {allowed}.

What each category means:
- pediatric: an infant, child, or adolescent (roughly under 18).
- ob_gyn: a pregnant patient, or a presentation centred on obstetric/gynaecological \
context.
- surgical: a patient whose context is defined by recent or planned surgery / a \
surgical presentation.
- geriatric: an older adult (roughly 65+), especially with frailty, polypharmacy, or \
functional-decline context.
- adult_general: any other adult, AND the safe default whenever the context does not \
clearly indicate one of the above.

CRITICAL RULES:
- Classify from the patient description only. Do NOT infer age, sex, pregnancy, or \
population from a chief complaint — you are not given one, and complaint wording is a \
poor, risky signal for population.
- If the description is empty, vague, or lacks age/sex/population-specific detail, \
classify as adult_general and set assumed_default=true. Do NOT guess a narrower \
category from thin information.
- Set assumed_default=true ONLY when you fell back to adult_general due to \
insufficient information. If you chose adult_general (or any other category) \
confidently from real stated detail, set assumed_default=false.
- Always explain your choice in `reasoning`, citing the specific detail you used (or \
stating that none was available)."""
    user_prompt = (
        f"Patient description: {patient_context}\n\n"
        f"Classify this patient's population category."
    )

    result = cast(
        _CategoryClassification,
        await call_agent(
            model=HISTORY_CLASSIFICATION_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=_CategoryClassification,
        ),
    )

    # Enforce the invariant "assumed_default implies adult_general" in code: if the
    # model contradicts itself (flags a fallback but names a narrow category), trust
    # the safe default the prompt mandates, not the narrow guess.
    if result.assumed_default and result.category is not PatientCategory.ADULT_GENERAL:
        return (PatientCategory.ADULT_GENERAL, result.reasoning, True)
    return (result.category, result.reasoning, result.assumed_default)


async def generate_checklist(category: PatientCategory) -> list[HistoryQuestion]:
    """Draft a general-history checklist from scratch for a category with no cached
    entry. ONE call_agent() call, routed to HISTORY_GENERATION_MODEL (strong tier —
    generated once ever per category, cached permanently; see config.py). Does NOT
    persist — that's save_checklist's job, kept separate for the same reason
    generate_framework/save_framework are separate.
    """
    system_prompt = f"""You are the History Agent in a clinical history-taking \
assistant. Produce the GENERAL-history checklist for the '{category.value}' patient \
population: the background-history questions a careful clinician asks EVERY patient in \
this population, regardless of their specific complaint. You assist history-taking; \
you do NOT diagnose.

This checklist is population-level and complaint-independent — the same for every \
patient in this category. Do NOT ask about any specific chief complaint or symptom.

Cover the standard general-history domains, ADAPTED to this population:
- Past medical history
- Current medications
- Allergies
- Smoking / alcohol / substance use (social history)
- Family history
- Baseline functional status

Adapt them to '{category.value}'. For example: pediatric should replace adult social \
history with developmental milestones, immunizations, birth/perinatal history, and \
ask about the carer; ob_gyn should add obstetric and menstrual history; geriatric \
should add falls, cognition, continence, and baseline independence/ADLs; surgical \
should add prior anaesthetic history, bleeding/clotting history, and fasting/relevant \
pre-operative background. Produce roughly 6–10 questions.

For each question:
- question_text: the question the clinician asks, phrased for THIS population.
- rationale: why this matters for THIS population (concrete, not a restatement).
- id: a short placeholder like "1", "2" — these are reassigned to authoritative \
namespaced ids after you respond, so don't overthink them.

Ground everything in standard clinical practice; do not fabricate exotic content."""
    user_prompt = (
        f"Produce the general-history checklist for the '{category.value}' population."
    )

    result = cast(
        _ChecklistDraft,
        await call_agent(
            model=HISTORY_GENERATION_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=_ChecklistDraft,
        ),
    )

    # Reassign authoritative, namespaced ids in code (don't trust the model's): the id
    # must be globally unique AND carry the history prefix so the re-scoring loop can
    # route it (HISTORY_QUESTION_ID_PREFIX). Category is part of the id for readability
    # in traces, e.g. "histq-pediatric-1".
    return [
        question.model_copy(
            update={"id": f"{HISTORY_QUESTION_ID_PREFIX}{category.value}-{index}"}
        )
        for index, question in enumerate(result.questions, start=1)
    ]


async def save_checklist(
    category: PatientCategory, questions: list[HistoryQuestion]
) -> None:
    """Persist a freshly generated checklist under the category key so every future
    patient in this population loads it instead of regenerating. Thin wrapper over
    history_store.save_checklist — its own tool for the same uniform-interface reason
    as the Framework Agent's save_framework."""
    history_store.save_checklist(category, questions)
