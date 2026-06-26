"""Framework tools — the actions the Framework Agent's loop (framework_agent.py)
can take. Each function is one tool the agent calls; the docstrings ARE the
interface the agent's reasoning depends on, not just internal notes (same
tool-design standard as the rest of this codebase).

Three tools:
  - match_cached_framework  — semantic "have we already got one of these?" check.
  - generate_framework      — draft a brand-new framework (the only LLM-authoring
                              step, routed to the strongest model).
  - save_framework          — persist a freshly generated framework to the cache.

Only `generate_framework` and `match_cached_framework` call an LLM; both go through
the existing `call_agent()` so there is exactly ONE AI-calling code path in the
project (CLAUDE.md Section 7). `save_framework` is a thin wrapper over the storage
layer — it exists as its own tool purely so the agent loop has a uniform tool-call
interface across all three actions, rather than inlining a store call mid-loop.
"""

from typing import cast

from pydantic import BaseModel

from app.agents.frameworks.chest_pain import CHEST_PAIN_ARMS
from app.config import FRAMEWORK_GENERATION_MODEL, FRAMEWORK_MATCH_MODEL
from app.core import framework_store
from app.core.call_agent import call_agent
from app.models import Framework


class FrameworkMatch(BaseModel):
    """Small dedicated response contract for the semantic-match call. A nullable
    field rather than a sentinel string so "no match" is structurally explicit and
    can't be confused with a real complaint name."""

    # The EXACT cached complaint string this new complaint matches, or null if none.
    matched_complaint: str | None


def _chest_pain_style_example() -> str:
    """Render a few real chest-pain arms verbatim as an in-prompt style example for
    `generate_framework`.

    Calibration matters more than instructions here: telling the model "use
    pathophysiological categories with concrete risk factors" is vaguer than simply
    SHOWING it the proven hand-tuned framework's shape and density. We pick a mix
    that includes both a red_flag=True arm and a red_flag=False one so the model sees
    that red_flag is an honest per-arm judgment, not always-true. Read straight from
    CHEST_PAIN_ARMS so this example can never drift from the real seeded content.
    """
    # Cardiac (red_flag True), Pulmonary Embolism (True), GERD/Esophageal (False).
    example_names = {"Cardiac (ACS / Ischemic)", "Pulmonary Embolism", "GERD / Esophageal"}
    blocks: list[str] = []
    for arm in CHEST_PAIN_ARMS:
        if arm.name not in example_names:
            continue
        factors = "\n".join(f"      - {rf}" for rf in arm.risk_factors)
        blocks.append(
            f"  - name: {arm.name}\n"
            f"    red_flag: {str(arm.red_flag).lower()}\n"
            f"    risk_factors:\n{factors}"
        )
    return "\n".join(blocks)


async def match_cached_framework(new_complaint: str) -> str | None:
    """Check whether an already-cached framework semantically matches this new
    complaint, even when the wording differs (e.g. "cephalgia" should match an
    existing "headache" entry; "SOB" should match "shortness of breath").

    Loads the current cached complaint list, then makes ONE small LLM call asking
    which (if any) cached complaint the new one refers to. Returns the matched
    canonical complaint string (usable directly as a cache key), or None if nothing
    matches — INCLUDING when the cache is empty, in which case it short-circuits with
    no LLM call at all. Routed to FRAMEWORK_MATCH_MODEL (cheap/fast) — this is a
    frequent, low-stakes judgment, same tier reasoning as TRIAGE_MODEL.
    """
    cached = framework_store.get_all_complaints()
    if not cached:
        # Nothing to match against — don't spend an LLM call to learn the obvious.
        return None

    candidates = "\n".join(f"- {c}" for c in cached)
    system_prompt = (
        "You are the cache-matching step of a clinical history-taking assistant. "
        "You are given a NEW chief complaint and a list of chief complaints that "
        "already have a cached diagnostic framework. Decide whether the new "
        "complaint refers to the SAME clinical chief complaint as one of the cached "
        "ones — accounting for synonyms, lay terms, abbreviations, spelling "
        "variants, and medical vs colloquial wording (e.g. 'cephalgia' = "
        "'headache', 'SOB' = 'shortness of breath', 'tummy ache' = 'abdominal "
        "pain'). Only match when it is genuinely the same presenting complaint, not "
        "merely a related or overlapping one (e.g. 'chest pain' and 'shortness of "
        "breath' are DIFFERENT complaints even though they overlap clinically). "
        "If it matches one, return that cached complaint string EXACTLY as it "
        "appears in the list, verbatim. If none match, return null."
    )
    user_prompt = (
        f"New complaint: {new_complaint}\n\n"
        f"Cached complaints:\n{candidates}\n\n"
        f"Which cached complaint (if any) does the new one refer to?"
    )

    result = await call_agent(
        model=FRAMEWORK_MATCH_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=FrameworkMatch,
    )
    matched = cast(FrameworkMatch, result).matched_complaint

    # Defensive guard: only honor a match that is ACTUALLY one of the candidates we
    # offered. If the model returns a near-miss or paraphrase that isn't a real key,
    # treat it as no-match (fail safe to "generate") rather than handing a phantom
    # key downstream that get_framework would just miss on.
    if matched is not None and matched in cached:
        return matched
    return None


async def generate_framework(complaint: str) -> Framework:
    """Draft a brand-new diagnostic-arm framework from scratch for a complaint that
    has no cached match. ONE call_agent() call, routed to FRAMEWORK_GENERATION_MODEL
    (the strongest tier — this result is cached permanently, so quality on this one
    call matters more than cost; see config.py).

    Prompted to match the quality bar of the hand-tuned chest_pain.py framework:
    real pathophysiological diagnostic arms (categories, not symptoms restated as
    arms), concrete risk factors a clinician would actually ask about, and an honest
    red_flag per arm. Does NOT persist the result — that's save_framework's job, kept
    separate so the agent loop controls exactly WHEN persistence happens.
    """
    system_prompt = f"""You are the Framework Agent in a clinical history-taking \
assistant. Given a chief complaint, you produce the diagnostic-arm FRAMEWORK for it: \
the set of pathophysiological categories a clinician reasons through when a patient \
presents with that complaint, each with the risk factors that raise its relevance. \
You assist history-taking; you do NOT diagnose.

This framework is complaint-level and patient-independent — it is the SAME for every \
patient with this complaint. Do NOT score anything, do NOT write questions, and do \
NOT reference any specific patient: a later agent scores these arms against an \
individual patient. Your job is only the framework.

Requirements:
- Produce diagnostic ARMS that are pathophysiological CATEGORIES (e.g. "Cardiac", \
"Pulmonary Embolism", "Musculoskeletal"), NOT symptoms or the complaint restated. \
Cover the clinically important differentials for this complaint, including the \
can't-miss ones, the way a careful generalist clinician would — typically 5 to 8 arms.
- For each arm give 5 to 12 CONCRETE risk factors: plain-language features (history, \
risk factors, pain character, associated symptoms, demographics) that would RAISE \
that arm's relevance for a given patient. Make them specific and askable in a \
history, like the example below — not vague one-word labels.
- Set red_flag to true ONLY for genuinely time-critical, life-threatening "can't-miss" \
arms (the ones that must never be silently dropped even when unlikely). Be honest: do \
NOT mark an arm red_flag just to seem cautious — inflating it is safety theater that \
makes the flag meaningless. Most complaints have a small number of true red-flag arms \
alongside several non-urgent ones.

Here is the proven, hand-tuned framework for "chest pain" as a STYLE and DENSITY \
example — match this level of concreteness and the honest mix of red_flag values, \
but produce arms appropriate to the ACTUAL complaint you are given (do not copy these \
arms unless they genuinely apply):

{_chest_pain_style_example()}

This is a generalist, teaching-level assistant: ground the framework in standard \
clinical reasoning, and do not fabricate exotic or unsafe content."""

    user_prompt = (
        f"Chief complaint: {complaint}\n\n"
        f"Produce the diagnostic-arm framework for this complaint."
    )

    result = await call_agent(
        model=FRAMEWORK_GENERATION_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=Framework,
    )
    framework = cast(Framework, result)

    # Authoritative in code: the cache key is OUR canonical complaint, not whatever
    # string the model chose to echo into the complaint field. Same principle as
    # rescore.py setting chief_complaint from the caller rather than the model.
    return framework.model_copy(update={"complaint": complaint})


async def save_framework(complaint: str, framework: Framework) -> None:
    """Persist a freshly generated framework under the canonical complaint key so
    every FUTURE patient with this complaint loads it instead of regenerating it.

    Thin wrapper over framework_store.save_framework — it exists as its own tool
    (rather than the agent loop calling the store directly) so all three of the
    agent's actions share one uniform tool-call interface.
    """
    framework_store.save_framework(complaint, framework)
