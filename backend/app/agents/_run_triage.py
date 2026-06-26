"""Terminal runner for the Triage Agent — the first visible product output.

No FastAPI route, no UI: just a script that calls the real agent and prints its
output readably. Run from backend/ so `app` imports resolve:

    PYTHONPATH=. uv run python app/agents/_run_triage.py

Edit the two constants below to try a different scenario.
"""

import asyncio

from app.agents.framework_agent import resolve_framework
from app.agents.triage import run_triage

# One hardcoded chest-pain scenario for now. Edit these to test other patients.
CHIEF_COMPLAINT = "chest pain"
PATIENT_CONTEXT = (
    "62-year-old male, smoker, pain worse on exertion, radiates to left arm"
)


async def main() -> None:
    # Resolve the framework first (cache hit for a seeded complaint), then triage —
    # mirrors what the /api/triage route now does.
    framework = await resolve_framework(CHIEF_COMPLAINT)
    result = await run_triage(framework, CHIEF_COMPLAINT, PATIENT_CONTEXT)

    print(f"Chief complaint: {result.chief_complaint}")
    print(f"Patient: {PATIENT_CONTEXT}\n")

    # Sort by relevance so the most likely arms read first.
    for arm in sorted(result.arms, key=lambda a: a.relevance_score, reverse=True):
        print(f"{arm.name:<28} {arm.relevance_score:>4.2f}   {arm.status}")
        print(f"  {arm.reasoning}\n")


if __name__ == "__main__":
    asyncio.run(main())
