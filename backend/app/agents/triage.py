"""Triage Agent — the first real agent in the project.

Its scope is deliberately narrow (CLAUDE.md Section 6, point 1): given a chief
complaint and a description of THIS specific patient, it scores how relevant each
diagnostic arm is and explains why. It does NOT generate history-taking questions
— that is the Question Generator Agent's job in a later step. Keeping that boundary
sharp is part of what makes the "multi-agent" claim honest rather than a single
prompt wearing several hats.

The clinical knowledge comes entirely from the hardcoded framework in
`frameworks/chest_pain.py` (CLAUDE.md Section 4) — the model is told to reason
within that framework, not to invent arms from its own training.
"""

from typing import cast

from app.agents.frameworks.chest_pain import CHEST_PAIN_ARMS
from app.config import TRIAGE_MODEL
from app.core.call_agent import call_agent
from app.models import TriageOutput


def _format_framework() -> str:
    """Render the chest pain framework into clear prompt text.

    Only `name` and `risk_factors` are surfaced to the model. `red_flag` is
    intentionally withheld here: triage scores RELEVANCE to the patient, and
    consequence/can't-miss handling belongs to the future Prioritization agent —
    feeding red-flag status in now would blur the agent boundary and could bias the
    model into inflating scores for dangerous-but-unlikely arms.
    """
    blocks: list[str] = []
    for arm in CHEST_PAIN_ARMS:
        factors = "\n".join(f"    - {rf}" for rf in arm.risk_factors)
        blocks.append(f"{arm.name}\n{factors}")
    return "\n\n".join(blocks)


def _build_system_prompt() -> str:
    return f"""You are the Triage Agent in a clinical history-taking assistant. \
You help a clinician by scoring how relevant each diagnostic arm is for the \
SPECIFIC patient in front of them. You assist history-taking; you do NOT diagnose, \
and the clinician remains the decision-maker.

Reason ONLY within the diagnostic arms defined in the framework below. Do not \
invent new arms, rename them, or drop any — score every arm listed, even ones that \
end up with a low score, so the clinician sees the full differential.

For each arm:
- Set relevance_score between 0 and 1, reflecting how much THIS patient's details \
match that arm's risk factors. Patient specifics must actively change the scores — \
a 62-year-old smoker with exertional pain and a 22-year-old with reproducible chest \
wall pain should get very different weightings.
- Write a short reasoning string: a brief, factor-based justification citing the \
specific patient details that raised or lowered the score (e.g. "Age >50, smoker, \
exertional radiating pain"). Keep it to a phrase or one sentence, not a paragraph.
- Set status to "active" for every arm at this stage.
- Set questions to an EMPTY LIST ([]) for every arm. You must NOT generate any \
history-taking questions — that is a different agent's job. This is a hard \
requirement: questions must be [] for all arms.

Diagnostic arm framework (chest pain):

{_format_framework()}"""


async def run_triage(chief_complaint: str, patient_context: str) -> TriageOutput:
    """Score the diagnostic arms for a chief complaint and a specific patient.

    `patient_context` is kept as a plain free-text string for the MVP (the quick
    clarifier info from CLAUDE.md Section 5 step 2) rather than a structured patient
    model. See the build report — this is flagged as something we may want to
    formalize into its own contract later, not silently decided here.
    """
    system_prompt = _build_system_prompt()
    user_prompt = (
        f"Chief complaint: {chief_complaint}\n"
        f"Patient: {patient_context}\n\n"
        f"Score every diagnostic arm for this patient."
    )

    result = await call_agent(
        model=TRIAGE_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=TriageOutput,
    )

    # call_agent is generic over BaseModel; here the validated instance is concretely
    # a TriageOutput, so we narrow the type for callers and type-checkers.
    return cast(TriageOutput, result)
