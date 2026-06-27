"""Suggestion Agent — rank "what to ask next" from already-existing questions.

WHY THIS IS AN AGENT, NOT A SORT (the justification for spending an LLM call here):
"top question per arm, sorted by arm score" is a deterministic ranking and would need
no model. The real decision is subtler — given the whole case (every arm's score, the
momentum from the last re-score, what general history is already known, which arms are
red-flag), which ~N questions would most efficiently move the differential RIGHT NOW,
INCLUDING the judgment that an arm whose score has cratered may not be worth surfacing
a question for at all even if it still has unanswered ones. That is a clinical-reasoning
judgment over the whole case — the same kind prioritization.py already makes — so it
gets its own small agent.

Scope is narrow (CLAUDE.md Section 6): this agent SELECTS and ORDERS already-generated
questions and writes a one-line justification for each. It does NOT generate new
questions, re-score arms, or diagnose. Routed cheap/fast (SUGGESTION_MODEL): the hard
reasoning already happened upstream, and a poor pick self-corrects on the next re-score.

Don't-trust-the-model discipline (same as rescore_arms' merge): everything identity- or
safety-bearing is recomputed in code after the call — question_text is copied from the
real pool, is_history_question/is_red_flag/source_arms are derived in code, and any
suggestion whose id isn't in the candidate pool is dropped. The model only chooses WHICH
ids, in what ORDER, with what justification.
"""

import logging
from typing import cast

from app.config import SUGGESTION_MODEL, SUGGESTION_POOL_SIZE
from app.core.call_agent import call_agent
from app.models import (
    DiagnosticArm,
    HistoryAnswer,
    HistoryChecklist,
    ScoreTransition,
    SuggestedQuestion,
    SuggestionBatch,
    is_history_question_id,
)

logger = logging.getLogger(__name__)

# A candidate pool entry: question_id -> (question_text, home_arm_name | None). A None
# home arm marks a general-history question (not tied to any arm).
PoolEntry = tuple[str, str | None]


def _build_system_prompt(pool_size: int, red_flag_arm_names: set[str]) -> str:
    red_flags = ", ".join(sorted(red_flag_arm_names)) or "(none marked)"
    return f"""You are the Suggestion Agent in a clinical history-taking assistant. \
You assist history-taking; you do NOT diagnose, and the clinician remains the \
decision-maker.

Your job: from a fixed pool of ALREADY-EXISTING, unanswered questions, select the \
ones most worth asking NEXT and put them in priority order, with a one-line reason for \
each. You are NOT generating new questions, NOT re-scoring arms, and NOT diagnosing — \
the scoring already happened upstream. You only choose what to surface now.

This is a SUGGESTION POOL the clinician picks from freely — NOT a sequence to enforce. \
They may ignore any suggestion and ask their own questions instead. Rank by what would \
most efficiently move the differential for THIS patient right now.

How to choose:
- Return AT MOST {pool_size} suggestions, best first. You may return FEWER — if the \
remaining questions belong only to arms that have sunk low enough that asking them is \
not worth the clinician's attention, leave them out. Do NOT pad the list to hit a \
count; a shorter, sharper pool is better than a padded one. This judgment — when an \
arm is no longer worth a question — is the main reason you exist rather than a sort.
- Weigh SCORE MOMENTUM: an arm whose score just moved sharply often deserves a \
confirmatory or clarifying follow-up.
- Weigh RED-FLAG status. These arms are time-critical, can't-miss: {red_flags}. A \
red-flag arm's screening questions deserve weight INDEPENDENT of its raw likelihood — \
likelihood is not the same as priority for a can't-miss diagnosis (the same principle \
the re-scoring agent uses: a low score does not mean "safe to ignore").
- A question can be relevant to more than one arm; name all the arms it genuinely \
serves in source_arms (use the EXACT arm names given). General-history questions are \
not tied to an arm.

Hard rules:
- question_id in EVERY suggestion MUST be copied EXACTLY from the candidate pool below. \
Do NOT invent ids, and do NOT suggest anything not in the pool. (Anything that doesn't \
match the pool is discarded.)
- Do NOT suggest a question that has already been answered. The pool below is already \
limited to unanswered questions; keep it that way.
- justification: ONE short clinical line (e.g. "would localize the nerve root level"), \
not a paragraph.
- Order the list from most to least worth asking next."""


def _build_user_prompt(
    chief_complaint: str,
    active_arms: list[DiagnosticArm],
    history_answers: list[HistoryAnswer],
    transitions: list[ScoreTransition],
    pool: dict[str, PoolEntry],
    red_flag_arm_names: set[str],
) -> str:
    arm_lines = "\n".join(
        f"- {arm.name} | score {arm.relevance_score:.2f}"
        f"{' | RED FLAG' if arm.name in red_flag_arm_names else ''} | {arm.reasoning}"
        for arm in active_arms
    )

    if transitions:
        momentum_lines = "\n".join(
            f"- {t.arm_name}: {t.old_score:.2f} -> {t.new_score:.2f} "
            f"({t.new_score - t.old_score:+.2f})"
            for t in transitions
        )
    else:
        momentum_lines = "(no scores have moved yet — this is the start of the interview)"

    if history_answers:
        history_lines = "\n".join(
            f'- "{h.question_text}" -> "{h.answer_text}"' for h in history_answers
        )
    else:
        history_lines = "(none recorded yet)"

    pool_lines = "\n".join(
        f"[{qid}] "
        f"({home_arm or 'General history'}"
        f"{' — RED FLAG arm' if home_arm in red_flag_arm_names else ''}) "
        f"{text}"
        for qid, (text, home_arm) in pool.items()
    )

    return (
        f"Chief complaint: {chief_complaint}\n\n"
        f"Current active diagnostic arms:\n{arm_lines}\n\n"
        f"Score momentum from the last answer(s):\n{momentum_lines}\n\n"
        f"General history already collected:\n{history_lines}\n\n"
        f"Candidate questions you may suggest (use the exact id in brackets):\n"
        f"{pool_lines}\n\n"
        f"Select and rank the questions most worth asking next."
    )


def _merge_suggestions(
    raw: SuggestionBatch,
    pool: dict[str, PoolEntry],
    valid_arm_names: set[str],
    red_flag_arm_names: set[str],
    pool_size: int,
) -> SuggestionBatch:
    """Pure, deterministic validation/merge of the model's raw output (NO AI call).

    Trust the model only for WHICH ids, their ORDER, and the justification text.
    Everything else is rebuilt from authoritative inputs:
      - drop any suggestion whose id isn't in the candidate pool (and de-dup repeats);
      - copy question_text from the pool, not the model's echo;
      - is_history_question via is_history_question_id (code, authoritative);
      - source_arms = the question's true home arm plus any REAL arms the model named
        (invented arm names dropped); empty for history questions;
      - is_red_flag = does source_arms intersect the red-flag arm set;
      - truncate to pool_size (the model may return more; never fewer is forced).
    Kept as a standalone pure function precisely so it can be unit-tested without an
    LLM call (see backend/tests/test_suggestion_merge.py).
    """
    merged: list[SuggestedQuestion] = []
    seen: set[str] = set()
    for suggestion in raw.suggestions:
        qid = suggestion.question_id
        if qid not in pool:
            logger.warning(
                "Suggestion Agent returned unknown question_id %r; dropping.", qid
            )
            continue
        if qid in seen:
            continue  # model listed the same id twice — keep the first (higher-ranked).
        seen.add(qid)

        question_text, home_arm = pool[qid]
        is_history = is_history_question_id(qid)
        if is_history:
            source_arms: list[str] = []
        else:
            arms = {a for a in suggestion.source_arms if a in valid_arm_names}
            if home_arm is not None:
                arms.add(home_arm)  # the home arm is always relevant, even if unnamed.
            source_arms = sorted(arms)
        is_red_flag = bool(set(source_arms) & red_flag_arm_names)

        merged.append(
            SuggestedQuestion(
                question_id=qid,
                question_text=question_text,
                source_arms=source_arms,
                justification=suggestion.justification.strip(),
                is_red_flag=is_red_flag,
                is_history_question=is_history,
            )
        )
        if len(merged) >= pool_size:
            break  # hard cap — see config.SUGGESTION_POOL_SIZE.

    return SuggestionBatch(suggestions=merged)


async def suggest_questions(
    chief_complaint: str,
    active_arms: list[DiagnosticArm],
    history_checklist: HistoryChecklist | None,
    history_answers: list[HistoryAnswer],
    red_flag_arm_names: set[str],
    transitions: list[ScoreTransition],
    pool_size: int = SUGGESTION_POOL_SIZE,
) -> SuggestionBatch:
    """Rank which already-existing unanswered questions to surface next.

    `active_arms` must already be the ACTIVE arms (deprioritized ones excluded by the
    caller via orchestration._active_arms — not re-derived here). The candidate pool is
    every unanswered arm question across those arms PLUS every general-history question
    not yet answered. `transitions` carries the score momentum from the same re-score
    this is called after (empty at interview start). All the state reasoned over is
    passed in — this is not a tool-calling agent.
    """
    # Build the candidate pool: id -> (text, home_arm | None). Only unanswered items.
    pool: dict[str, PoolEntry] = {}
    for arm in active_arms:
        for question in arm.questions:
            if not question.answered:
                pool[question.id] = (question.text, arm.name)

    answered_history_ids = {h.id for h in history_answers}
    if history_checklist is not None:
        for hq in history_checklist.questions:
            if hq.id not in answered_history_ids:
                pool[hq.id] = (hq.question_text, None)

    # Nothing left to ask -> empty pool, and no point spending an LLM call.
    if not pool:
        return SuggestionBatch(suggestions=[])

    valid_arm_names = {arm.name for arm in active_arms}
    system_prompt = _build_system_prompt(pool_size, red_flag_arm_names)
    user_prompt = _build_user_prompt(
        chief_complaint, active_arms, history_answers, transitions, pool, red_flag_arm_names
    )

    raw = cast(
        SuggestionBatch,
        await call_agent(
            model=SUGGESTION_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=SuggestionBatch,
        ),
    )

    return _merge_suggestions(
        raw, pool, valid_arm_names, red_flag_arm_names, pool_size
    )
