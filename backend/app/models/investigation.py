"""Investigation Suggestion contracts: the on-demand "what would you order now" pane.

This is a THIRD kind of clinician action, distinct from both history-taking answers
(/api/answers) and the ranked question pool (suggestion.py): an explicit, on-demand
snapshot of tests/imaging worth considering given everything gathered so far. It does
NOT diagnose, does NOT auto-refresh, and does NOT participate in the answer/re-score
loop — the clinician asks for it, reads it, and asks again later if they like.

Pattern notes (consistent with the rest of app/models, especially suggestion.py):
- `InvestigationSuggestion` co-locates its one-line `reasoning` with the test it
  justifies, the same way `SuggestedQuestion` keeps its `justification` next to the
  question and `DiagnosticArm` keeps `reasoning` next to `relevance_score` (clinical.py
  module docstring). One short line, not a paragraph — this is a glance-able list.
- `arm_name` is an IDENTITY-bearing field and is therefore NOT trusted from the model:
  the agent's caller validates it in code against the actual top-N arm list (an invented
  arm name, or one outside that list, is DROPPED), and forces `routine` items' arm_name
  to None — exactly the don't-trust-the-model discipline `_merge_suggestions` applies to
  `SuggestedQuestion.source_arms`. See `investigation_agent._merge_investigations`.
- There is deliberately NO score field. Like `SuggestedQuestion` (and unlike
  `DiagnosticArm`), this output is a SELECTION, not a set of independently-scored items —
  a fake number to sort by would be the meaningless-field drift history.py warns against.
"""

from pydantic import BaseModel


class InvestigationSuggestion(BaseModel):
    """One test/imaging suggestion, with its one-line reasoning co-located (same pattern
    as SuggestedQuestion.justification + DiagnosticArm.reasoning)."""

    # The test or imaging name, e.g. "CT pulmonary angiography", "ECG", "D-dimer".
    name: str

    # ONE short clinical sentence — why this test, for this case. Intentionally terse
    # (this is a list a clinician scans mid-case, not a teaching explanation).
    reasoning: str

    # Which diagnostic arm this suggestion is tied to. None for ROUTINE workup (baseline
    # tests justified by the chief complaint alone, regardless of which diagnosis is
    # right); SET to a real arm name for SPECIALIZED workup (a test chosen to rule a
    # specific top-scoring arm in/out). Authoritative in CODE, never trusted from the
    # model: the caller validates a SPECIALIZED arm_name against the actual top-N arm
    # list and drops an invented one, and forces every ROUTINE item's arm_name to None —
    # the same discipline `SuggestedQuestion.source_arms` gets in _merge_suggestions.
    arm_name: str | None


class InvestigationBatch(BaseModel):
    """The full output of ONE Investigation Suggestion Agent call: the two workup tiers,
    plus the snapshot point at which they were generated.

    The two lists are kept SEPARATE (rather than one list with a tier flag) because the
    frontend renders them as two distinct sections, and the routine/specialized split is
    the agent's whole job — collapsing them would lose the distinction the prompt's
    worked examples exist to enforce.
    """

    # Baseline workup for the chief complaint + patient, regardless of diagnosis.
    # `arm_name` is always None here (enforced in code, not merely prompted).
    routine: list[InvestigationSuggestion]

    # Per-arm workup for the top-scoring arms. Every item's `arm_name` is always SET to
    # one of the top-N arms passed to the agent (enforced in code — an item naming an
    # arm outside that set is dropped).
    specialized: list[InvestigationSuggestion]

    # The TOTAL answered-question count (arm answers + history answers) at the moment
    # this batch was generated. The frontend keeps it to show a staleness marker ("N new
    # answers since") when more questions are answered after a snapshot — this pane does
    # NOT auto-refresh, so it needs a way to say "this is from earlier in the interview".
    generated_at_answer_count: int
