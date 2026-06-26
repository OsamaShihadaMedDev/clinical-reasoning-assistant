"""One-time seed: write the hand-tuned chest-pain framework into the cache as row one.

Run ONCE manually after the Framework Agent migration, from `backend/`:

    PYTHONPATH=. uv run python scripts/seed_chest_pain_framework.py

Why this exists instead of just letting chest pain flow through generate_framework():
the existing CHEST_PAIN_ARMS data (agents/frameworks/chest_pain.py) is hand-tuned by a
near-qualified physician and proven live end-to-end. Regenerating it with an LLM would
be a pure quality regression for zero benefit. So we convert the existing dataclasses
straight into the new Pydantic Framework and persist them with NO agent call and NO LLM
involved at all — the cache hit path then serves this exact, reviewed content to every
chest-pain patient forever.

`chest_pain.py` stays in the repo after this (it is the historical source of truth for
what was seeded, and is still read as the style example inside framework_tools.py); it
is simply no longer the live framework source for triage.
"""

from app.agents.frameworks.chest_pain import CHEST_PAIN_ARMS
from app.core import framework_store
from app.models import Framework, FrameworkArm

_COMPLAINT = "chest pain"


def main() -> None:
    # Convert each frozen ChestPainArm dataclass into the validated FrameworkArm
    # contract. The fields map 1:1 (name, risk_factors, red_flag), so this is a pure
    # shape change — no content is altered, reordered, or dropped.
    arms = [
        FrameworkArm(
            name=arm.name,
            risk_factors=list(arm.risk_factors),
            red_flag=arm.red_flag,
        )
        for arm in CHEST_PAIN_ARMS
    ]
    framework = Framework(complaint=_COMPLAINT, arms=arms)

    # Persist directly through the store — no Framework Agent, no generate_framework.
    framework_store.save_framework(_COMPLAINT, framework)

    # Read it back to confirm the round-trip (serialize -> SQLite -> validate) works.
    stored = framework_store.get_framework(_COMPLAINT)
    assert stored is not None, "seed failed: framework not found after save"
    print(
        f"Seeded '{_COMPLAINT}' with {len(stored.arms)} arms "
        f"({sum(1 for a in stored.arms if a.red_flag)} red-flag). "
        f"Cached complaints now: {framework_store.get_all_complaints()}"
    )


if __name__ == "__main__":
    main()
