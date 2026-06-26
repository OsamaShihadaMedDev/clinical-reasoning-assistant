"""Triage Agent — the first real agent in the project.

Its scope is deliberately narrow (CLAUDE.md Section 6, point 1): given a chief
complaint and a description of THIS specific patient, it scores how relevant each
diagnostic arm is and explains why. It does NOT generate history-taking questions
— that is the Question Generator Agent's job in a later step. Keeping that boundary
sharp is part of what makes the "multi-agent" claim honest rather than a single
prompt wearing several hats.

The clinical knowledge comes entirely from the framework it is handed (CLAUDE.md
Section 4) — the model is told to reason WITHIN that framework's arms, not to invent
arms from its own training. That framework used to be a hardcoded chest-pain import;
it is now resolved per-complaint by the Framework Agent and passed in (see
`framework_agent.resolve_framework`), so this agent is no longer tied to one
complaint — only its data source changed, its job did not.
"""

from typing import cast

from app.config import TRIAGE_MODEL
from app.core.call_agent import call_agent
from app.models import Framework, TriageOutput


def _format_framework(framework: Framework) -> str:
    """Render the diagnostic-arm framework into clear prompt text.

    Only `name` and `risk_factors` are surfaced to the model. `red_flag` is
    intentionally withheld here: triage scores RELEVANCE to the patient, and
    consequence/can't-miss handling belongs to the Prioritization agent — feeding
    red-flag status in now would blur the agent boundary and could bias the model
    into inflating scores for dangerous-but-unlikely arms. (This withholding is why
    triage takes the rich `Framework`, which carries red_flag, but renders only two
    of its three fields.)
    """
    blocks: list[str] = []
    for arm in framework.arms:
        factors = "\n".join(f"    - {rf}" for rf in arm.risk_factors)
        blocks.append(f"{arm.name}\n{factors}")
    return "\n\n".join(blocks)


def _build_system_prompt(framework: Framework) -> str:
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

Diagnostic arm framework ({framework.complaint}):

{_format_framework(framework)}"""


async def run_triage(
    framework: Framework, chief_complaint: str, patient_context: str
) -> TriageOutput:
    """Score the diagnostic arms for a chief complaint and a specific patient.

    `framework` is the diagnostic-arm framework resolved for this complaint by the
    Framework Agent (cache hit or fresh generation). It replaces the old hardcoded
    chest-pain import: the agent now scores whatever arms it is handed, so it works
    for any complaint without code changes here. `framework.complaint` (the canonical
    complaint the framework was built for) may differ from `chief_complaint` (what the
    user actually typed, e.g. "cephalgia" vs the framework's "headache") — both are
    kept on purpose: the framework heading uses the canonical name, while the user
    prompt and the stored TriageOutput use the patient's own words.

    `patient_context` is kept as a plain free-text string for the MVP (the quick
    clarifier info from CLAUDE.md Section 5 step 2) rather than a structured patient
    model. See the build report — this is flagged as something we may want to
    formalize into its own contract later, not silently decided here.
    """
    system_prompt = _build_system_prompt(framework)
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
