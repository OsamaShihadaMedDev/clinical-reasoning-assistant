"""Clinical domain contracts: a single history-taking question, and the
diagnostic arm that groups questions under one pathophysiological category.

`DiagnosticArm` is the single most important model in the project. It deliberately
carries BOTH `relevance_score` and `reasoning` on the same model. This is the
CLAUDE.md Section 6a decision: explainability does not live in a separate
"Evidence Agent" pipeline stage (which would cost another full LLM round-trip for
value we can get more cheaply). Instead, the agent that produces the score also
produces the human-readable justification for it, in the same structured output.
Keeping them together is what lets the Trace Viewer (6b) show *why* a score is what
it is, and it is the exact field (`reasoning`) where RAG-sourced citations attach
in v2 — without restructuring the pipeline.

For the same reason, PROVENANCE lives on this model too (`source`): whether an arm was
discovered by the Framework Agent at triage or added by the clinician mid-interview is
clinically meaningful — it distinguishes "the system found this" from "the human caught
something the system missed" — and, like score/reasoning, it is a fact ABOUT the arm
that every consumer (UI badge, future audit) needs at the point the arm is rendered. It
belongs on the arm itself, not in some side table the consumer has to join against.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ClinicalQuestion(BaseModel):
    """One targeted history-taking question belonging to a diagnostic arm."""

    # Stable handle for this question. The frontend needs to reference a *specific*
    # question when the user checks it off ("patient answered"), and the re-scoring
    # loop (RescoreTrigger) identifies the answered question by this id — text alone
    # is not safe to match on, since two arms could phrase a question similarly.
    id: str

    # The literal question shown to the clinician during the interview.
    text: str

    # What this question rules in or out, e.g. "Rules in/out pulmonary embolism via
    # pleuritic pain pattern." This is CLAUDE.md Section 3's core product insight:
    # every question is labeled with its diagnostic intent so the user understands
    # *why* they are asking it, not just *what* to ask.
    diagnostic_intent: str

    # Whether the clinician has checked this question off as answered. Drives the
    # live summary panel and is the event that fires the re-scoring feedback loop.
    answered: bool = False

    # The captured answer, populated only once `answered` becomes True.
    # INVARIANT: this must stay None while `answered` is False. Pydantic does not
    # enforce cross-field invariants automatically — a `model_validator` could
    # enforce it later, but that is not necessary for the MVP, so it is left as a
    # documented contract rather than coded validation.
    answer_text: str | None = None


class DiagnosticArm(BaseModel):
    """One diagnostic arm (e.g. Cardiac, Pulmonary Embolism) and its questions.

    See the module docstring for why `relevance_score` and `reasoning` are
    co-located on this model rather than split into a separate agent.
    """

    # Human-readable arm label, e.g. "Cardiac", "Pulmonary Embolism".
    name: str

    # How relevant this arm is to the specific patient in front of the clinician.
    # Bounded to [0, 1] because it is a relevance *weight* used to rank/prioritize
    # arms, not a free-floating magnitude — an unbounded number would make scores
    # incomparable across arms and meaningless to the re-scoring loop. The bound is
    # enforced at the contract level so a misbehaving agent cannot emit e.g. 1.7.
    relevance_score: float = Field(ge=0, le=1)

    # The factors that produced the score, e.g. "Age >50, smoker, exertional
    # symptoms." This makes the score defensible instead of a black box, feeds the
    # Trace Viewer directly, and is the seam where RAG guideline citations get
    # attached in v2 (CLAUDE.md Section 4) — same field shape, no restructuring.
    reasoning: str

    # Whether the user has kept this arm active or pushed it down. Maps directly to
    # the activate/deprioritize control in the UI (CLAUDE.md Section 5, step 4).
    # A Literal (not a bare str) so only the two valid states are representable.
    status: Literal["active", "deprioritized"] = "active"

    # The questions generated for this arm by the Question Generator Agent. Defaults
    # to an empty list because the Triage Agent produces arms with NO questions on
    # initial fan-out (it only scores/reasons); questions are populated in a later,
    # separate step. See judgment-call note in the task report re: this default.
    questions: list[ClinicalQuestion] = Field(default_factory=list)

    # Provenance: did the Framework Agent discover this arm at triage time, or did the
    # clinician add it mid-interview because they suspected something the system missed?
    # Clinically meaningful to preserve, not just a UI label — see the module docstring
    # for why provenance-bearing fields belong on this model directly. Defaults to
    # "discovered" so every existing pipeline path (triage, re-score) stays correct
    # without change; only the /api/arm/custom path sets it to "clinician". Provenance is
    # authoritative in code (the Triage Agent's output is forced to "discovered"), never
    # taken from the model — the same discipline used for questions/chief_complaint.
    source: Literal["discovered", "clinician"] = "discovered"
