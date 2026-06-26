"""Framework Agent — resolve a diagnostic-arm framework for any chief complaint.

FIRST BRANCHING AGENT IN THIS CODEBASE (a note in the spirit of prioritization.py's
"deliberate deviation" comment): every agent so far — Triage, Question Generator,
Prioritization — always runs the SAME fixed sequence of structured-output calls on
every request. This one is different: it makes a real ReAct-style decision
(Thought -> Action -> Observation) and BRANCHES on the result of a tool call. It
takes one action (check the cache), observes the outcome (hit or miss), and only
then decides what to do next — return the cached framework, or generate and persist
a new one. That branch on a tool result is what makes this genuinely agentic rather
than another straight pipeline stage.

It is also deliberately TINY. There is exactly one decision point and a hard cap of
two tool calls, and that bound is enforced STRUCTURALLY — by the shape of the
if/else below — not by a max_iterations counter or a prompt politely asked to stop.
Building generic multi-step looping machinery here would be solving a problem this
loop doesn't have (CLAUDE.md Section 11: don't add machinery for sophistication's
sake). If you can run more than two tool calls by reading this function, that's a
bug; you shouldn't be able to.
"""

from app.agents.framework_tools import (
    generate_framework,
    match_cached_framework,
    save_framework,
)
from app.core import framework_store
from app.models import Framework


async def resolve_framework(complaint: str) -> Framework:
    """Resolve a Framework for any chief complaint: try the cache first via a
    semantic match, and only generate + persist a new one on a genuine miss.

    Bounded 1-or-2-call loop, not an open-ended agent:
      1. Action:      match_cached_framework(complaint)
      2. Observation: a matched cached complaint name, or None.
      3a. HIT  -> load it from the store and return it. (No generation.)
      3b. MISS -> generate a new framework, persist it, return it. (One LLM
                  generation call, then a pure DB write.)

    The branch is binary and resolved in a single pass — no retry loop, no further
    reasoning steps. The two arms of the `if` below ARE the entire control flow.
    """
    # --- Action + Observation: ask whether the cache already has this complaint. ---
    matched = await match_cached_framework(complaint)

    # --- Branch 3a: HIT. The matcher only returns a string that is a real cache
    #     key (it validates membership before returning), so this load normally
    #     succeeds. We still guard the None case: if the row somehow isn't there,
    #     we don't fail — we fall through to the MISS branch and regenerate, so this
    #     function always honors its contract of returning a Framework.
    if matched is not None:
        cached = framework_store.get_framework(matched)
        if cached is not None:
            return cached

    # --- Branch 3b: MISS (or the guarded edge above). Generate once, persist, return.
    #     Generation does NOT persist itself — we call save_framework explicitly here
    #     so the agent loop, not the generation tool, owns exactly when the cache is
    #     written. We save under the ORIGINAL complaint key (the store canonicalizes
    #     it), not `matched`, because on a miss there is no matched key.
    framework = await generate_framework(complaint)
    await save_framework(complaint, framework)
    return framework
