"""Framework contracts: the complaint-level diagnostic-arm template that the
Framework Agent resolves (loads or generates) BEFORE triage runs.

Why these are new Pydantic models rather than reusing the old frozen dataclass
(`ChestPainArm` in `agents/frameworks/chest_pain.py`): a framework used to be
hand-written Python source only, so a plain dataclass was enough — the shape was
guaranteed by the author. Frameworks are now ALSO produced by an LLM
(`generate_framework`) and round-tripped through SQLite as JSON, so they need the
same "fail loud on a bad shape" protection every other agent output in this
codebase gets. That is exactly what Pydantic validation buys, and a dataclass does
not.

Boundary note — FrameworkArm vs DiagnosticArm (in `clinical.py`):
- `FrameworkArm` is COMPLAINT-level. It is the same for every patient with this
  complaint: a category name, the risk factors a clinician would ask about, and an
  honest red_flag marker. No scores, no reasoning, no questions.
- `DiagnosticArm` is PATIENT-level. The Triage Agent produces it BY scoring a
  specific patient against a `FrameworkArm` list — it adds relevance_score,
  reasoning, status, and (later) questions.
Keeping them as two models, not one, is the same agent-contract boundary discipline
as the rest of the codebase: it makes it obvious at a glance which pipeline stage
owns which data. Do not merge them.
"""

from pydantic import BaseModel


class FrameworkArm(BaseModel):
    """One diagnostic arm within a chief-complaint framework, before any
    patient-specific scoring happens. This is framework-level data (the same for
    every patient with this complaint) — contrast with DiagnosticArm in
    clinical.py, which is the PATIENT-SPECIFIC scored/reasoned version the Triage
    Agent produces FROM this data.
    """

    # Arm label as the clinician thinks of it (e.g. "Cardiac (ACS / Ischemic)").
    # This becomes DiagnosticArm.name once the Triage Agent scores it.
    name: str

    # Plain-language factors that RAISE this arm's relevance for a given patient.
    # These are the actual clinical content the Triage Agent weighs against the
    # patient context — the same role ChestPainArm.risk_factors plays today.
    risk_factors: list[str]

    # True = time-critical / life-threatening "can't-miss" arm. Same meaning and
    # same downstream consumer as ChestPainArm.red_flag today: it is read by
    # `app/core/rescore.py` to build the red-flag arm-name set the Prioritization
    # Agent's safety check uses. It is deliberately NOT surfaced to the Triage Agent
    # (see triage.py's _format_framework docstring for why).
    red_flag: bool


class Framework(BaseModel):
    """A complete diagnostic-arm framework for one chief complaint. This is what
    the Framework Agent resolves (loads from cache or generates fresh) and what the
    Triage Agent consumes in place of the old hardcoded CHEST_PAIN_ARMS import.
    """

    # The chief complaint this framework is for. The canonical (lowercased, trimmed)
    # form is also the SQLite primary key the framework is cached under — see
    # `core/framework_store.py`, which owns that canonicalization.
    complaint: str

    # The diagnostic arms for this complaint. A list (not a dict keyed by name)
    # because order is meaningful for rendering and the arm name already serves as
    # the identity key downstream.
    arms: list[FrameworkArm]
