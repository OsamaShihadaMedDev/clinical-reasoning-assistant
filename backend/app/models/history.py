"""History Agent contracts: the general-history checklist collected BEFORE any
complaint-specific triage, and the population category that selects it.

These are a deliberately SEPARATE family of contracts from the Framework Agent's
`Framework`/`FrameworkArm` (and from `DiagnosticArm`/`ClinicalQuestion`). The two
agents answer different questions — "what COMPLAINT is this?" (Framework) vs "what
POPULATION is this patient?" (History) — and conflating them into one cache or one
contract would blur a real semantic boundary (same boundary discipline as the
Triage/Question-Generator/Prioritization split). So:

- `FrameworkArm` is complaint-level; `HistoryQuestion` is population-level.
- `HistoryAnswer` is intentionally NOT a `DiagnosticArm` or a `ClinicalQuestion`
  with a fake relevance_score: "patient smokes" / "no known allergies" are not
  scored against each other the way diagnostic arms are, so giving them a
  permanently-meaningless score field would mislead anyone reading the code later.
"""

from enum import Enum

from pydantic import BaseModel

# Question-id namespace for general-history questions. It is how the re-scoring loop
# (core/rescore.py) tells a history answer apart from an arm answer using only the
# answered question's id (Step 8): arm ids are "<arm-slug>-<n>" produced by the
# Question Generator, and a diagnostic-arm name never slugifies to start with this
# sentinel, so the two id spaces cannot collide. Centralized here (the history
# domain) so the assigner (history_tools.generate_checklist) and the detector
# (rescore.is_history_question_id) share one source of truth.
HISTORY_QUESTION_ID_PREFIX = "histq-"


def is_history_question_id(question_id: str) -> bool:
    """True if this id belongs to a general-history question (vs a diagnostic-arm
    question). The single routing predicate used by the re-scoring loop."""
    return question_id.startswith(HISTORY_QUESTION_ID_PREFIX)


class PatientCategory(str, Enum):
    """The fixed, small set of population categories general history-taking actually
    differs across. Deliberately NOT open-ended/agent-invented (unlike the chief-
    complaint cache, which is allowed to grow): there is no legitimate "infinite
    variety" of populations the way there is of complaint phrasing, so this list is
    locked and only grows by explicit human decision.

    A `str` Enum so it serializes to its plain value ("pediatric") over JSON/SSE and
    in the SQLite key without extra coercion.
    """

    PEDIATRIC = "pediatric"
    OB_GYN = "ob_gyn"
    SURGICAL = "surgical"
    GERIATRIC = "geriatric"
    # The safe-default bucket. MUST always exist and is the fallback target whenever
    # classification is uncertain (see history_tools.classify_patient_category).
    ADULT_GENERAL = "adult_general"


class HistoryQuestion(BaseModel):
    """One general-history question within a population checklist, before any patient
    has answered it. Framework-level (template) data — same for every patient in this
    category. Same relationship to `HistoryAnswer` that `FrameworkArm` has to a scored
    `DiagnosticArm`: this is the template, `HistoryAnswer` is what a specific patient
    produces from it."""

    # Stable handle, namespaced with HISTORY_QUESTION_ID_PREFIX (assigned in code by
    # generate_checklist, not trusted from the model) so the answer-submission flow can
    # route it through the same /api/answer endpoint the arm questions use.
    id: str

    # The literal question shown to the clinician.
    question_text: str

    # Why this is asked for THIS population — same spirit as ClinicalQuestion's
    # diagnostic_intent: the clinician sees *why*, not just *what*.
    rationale: str


class HistoryChecklist(BaseModel):
    """A complete general-history checklist for one population category. What the
    History Agent resolves (loads or generates) and what the UI renders as the
    General History card above the diagnostic arms."""

    category: PatientCategory

    # The checklist questions. This list (NOT assumed_default/category_reasoning) is
    # the only part that is cached per category — the two fields below describe a
    # specific classification, not the reusable checklist content.
    questions: list[HistoryQuestion]

    # True ONLY when classification FELL BACK to ADULT_GENERAL because patient_context
    # was empty or too thin to classify confidently — NOT true whenever ADULT_GENERAL
    # is the genuinely correct, context-supported classification. The UI uses this to
    # decide whether to show the "we had to guess" assumption note (Step 6/7), so it
    # must encode "did we have to guess," not merely "which category did we land on."
    assumed_default: bool

    # Always populated (even when assumed_default is False), mirroring how
    # TriageOutput/DiagnosticArm always carry reasoning alongside their structured
    # decision. When assumed_default is True this is the literal text the UI shows in
    # the assumption note.
    category_reasoning: str


class HistoryAnswer(BaseModel):
    """One answered general-history question for a specific patient. Its own small
    contract (see module docstring for why it is deliberately not a DiagnosticArm /
    scored question). Collected into session state and fed to the Prioritization
    Agent as plain question/answer context during re-scoring (Step 8)."""

    id: str
    question_text: str
    answer_text: str
