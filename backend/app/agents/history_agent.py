"""History Agent — resolve a general-history checklist for any patient, before the
Framework Agent / Triage run.

Sibling to the Framework Agent, same "cache-then-generate, bounded loop" discipline,
but with TWO independent decisions instead of one (this is the key difference, and why
the two steps below are kept visibly separate rather than collapsed):

  1. CLASSIFY the patient into a population category from free-text context. Its
     failure mode is "ambiguous/thin context" — handled by defaulting to
     adult_general, never by erroring.
  2. CACHE-CHECK that category. Its failure mode is "genuinely new category" — which
     should be rare, since the category enum is small and fixed, but is handled the
     same cache-miss way the Framework Agent handles a new complaint.

Those are different concerns, so they read as two steps here; conflating them would
make it harder to reason about either one later. The whole thing is still a fixed,
bounded sequence — at most one classification call plus one generation call, capped by
this function's own control flow, not by trusting a prompt or a max-iterations counter.

There is NO error path by design: an empty patient_context is an EXPECTED input
(classification falls back to adult_general), not an exceptional one, so this always
returns a usable HistoryChecklist.
"""

from app.agents.history_tools import (
    classify_patient_category,
    generate_checklist,
    save_checklist,
)
from app.core import history_store
from app.models import HistoryChecklist


async def resolve_history_checklist(patient_context: str) -> HistoryChecklist:
    """Resolve a HistoryChecklist for any patient_context: classify the population,
    then load a cached checklist or generate one on a genuine first-time miss.

    Bounded sequence:
      1. classify_patient_category(patient_context) -> (category, reasoning,
         assumed_default)
      2. history_store.get_checklist(category) -> cached questions, or None
      3a. HIT  -> assemble and return the checklist from the cached questions.
      3b. MISS -> generate_checklist(category), save_checklist(category, ...),
                  then assemble and return.

    `assumed_default` and `category_reasoning` come from THIS call's classification
    (step 1), never from the cache — the cache holds only the reusable questions, so a
    confident pediatric classification and a thin-context adult_general fallback can
    both reuse a cached checklist while still carrying the right per-call note.
    """
    # --- Decision 1: classify. Always succeeds (defaults to adult_general). ---
    category, category_reasoning, assumed_default = await classify_patient_category(
        patient_context
    )

    # --- Decision 2: cache-check that category, generating only on a real miss. ---
    questions = history_store.get_checklist(category)
    if questions is None:
        questions = await generate_checklist(category)
        await save_checklist(category, questions)

    # Assemble the full checklist: cached/generated questions + this call's own
    # classification note (NOT loaded from cache — see docstring).
    return HistoryChecklist(
        category=category,
        questions=questions,
        assumed_default=assumed_default,
        category_reasoning=category_reasoning,
    )
