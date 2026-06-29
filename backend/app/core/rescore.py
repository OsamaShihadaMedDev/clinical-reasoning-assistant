"""Re-scoring orchestration — the feedback loop's glue.

This closes the loop CLAUDE.md Section 5 step 5 / Section 6 point 3 describe: the user
checking off an answer doesn't just update a flag, it re-triggers the Prioritization
Agent to REVISE the earlier triage scores. This module is what turns a single answer
into (a) an updated interview state and (b) the ScoreTransition records the Trace
Viewer (Section 6b) will later render — the visible proof the loop did something.
"""

import asyncio
import re

from app.agents.prioritization import rescore_arms
from app.agents.suggestion_agent import suggest_questions
from app.core.orchestration import _active_arms, _qualifying_arms, ensure_arm_questions
from app.models import (
    AnsweredQuestion,
    ClinicalQuestion,
    DiagnosticArm,
    Framework,
    HistoryAnswer,
    HistoryChecklist,
    RescoreTrigger,
    ScoreTransition,
    SuggestionBatch,
    TriageOutput,
    is_history_question_id,
)

# DATA-SOURCE CHANGE (multi-complaint generalization): the red-flag arm names used by
# the Prioritization Agent's safety check are no longer a module-level constant baked
# from the single hardcoded chest-pain framework. Frameworks are now per-complaint and
# resolved at request time, so the can't-miss set must be derived PER SESSION from the
# same `Framework` that was resolved for that interview — passed in via `process_answer`
# below. This is the exact seam the old "wired in directly" comment predicted. Behavior
# for chest pain is identical (the seeded chest-pain framework has the same red_flag
# arms); only WHERE the set comes from changed.


def _find_question(triage: TriageOutput, question_id: str) -> ClinicalQuestion | None:
    """Locate an ARM question by id across ALL arms. Ids are globally unique (namespaced
    per arm by the Question Generator), so the first match is the only match."""
    for arm in triage.arms:
        for question in arm.questions:
            if question.id == question_id:
                return question
    return None


def _find_history_question_text(
    history_checklist: HistoryChecklist | None, question_id: str
) -> str:
    """Recover a general-history question's text by id from the session's checklist.
    Fails loud if absent — same fail-loud principle as the arm path: we will not
    re-score against an answer whose question we can't identify."""
    if history_checklist is not None:
        for question in history_checklist.questions:
            if question.id == question_id:
                return question.question_text
    raise ValueError(
        f"history question_id '{question_id}' not found in this session's checklist."
    )


async def build_suggestions(
    triage: TriageOutput,
    framework: Framework,
    history_checklist: HistoryChecklist | None,
    history_answers: list[HistoryAnswer],
    transitions: list[ScoreTransition],
) -> SuggestionBatch:
    """Assemble the Suggestion Agent's inputs from session state and run it.

    The SINGLE wiring point both the interview start (`/api/triage`, no transitions yet)
    and the re-score path use, so the input assembly isn't duplicated. Active arms come
    from the shared `orchestration._active_arms` filter (NOT the top-N `_qualifying_arms`
    — the suggestion pool ranks across ALL active arms, not just the auto-generated
    top N); the red-flag arm names are derived from the framework, the same source the
    re-score safety check uses.
    """
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}
    return await suggest_questions(
        chief_complaint=triage.chief_complaint,
        active_arms=_active_arms(triage),
        history_checklist=history_checklist,
        history_answers=history_answers,
        red_flag_arm_names=red_flag_arm_names,
        transitions=transitions,
    )


def validate_answer_ids(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    history_checklist: HistoryChecklist | None,
) -> None:
    """Read-only pre-flight: confirm EVERY answer's question_id resolves (an arm question
    in the triage, or a history question in the checklist). Raises ValueError on the
    first miss.

    The streaming /api/answers route calls this BEFORE opening the event stream, so a
    bad question_id is rejected with a synchronous HTTP 400 rather than a mid-stream
    `error` frame — mirroring how the missing-session 404 stays a normal HTTP error.
    Pure and side-effect-free (it does not mark anything answered).
    """
    for question_id, _ in answers:
        if is_history_question_id(question_id):
            _find_history_question_text(history_checklist, question_id)  # raises if absent
        elif _find_question(current_triage, question_id) is None:
            raise ValueError(
                f"question_id '{question_id}' not found in the current triage state."
            )


async def apply_batch_and_rescore(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    framework: Framework,
    history_checklist: HistoryChecklist | None,
    history_answers: list[HistoryAnswer],
) -> tuple[TriageOutput, list[ScoreTransition]]:
    """Record a batch of answers and run the SINGLE re-score (the old steps 1-4).

    Factored out of `process_answers` so the streaming endpoint can emit a `rescored`
    stage event right after this returns — before suggestions are ranked — without
    duplicating any logic. Mutates in place exactly as before: arm questions are marked
    answered on `current_triage`, and history answers in the batch are appended to
    `history_answers` (the session's running list). `history_answers` must be a real
    list (the caller defaults it).

    Each AnsweredQuestion carries its resolved question_text so rescore_arms never has to
    re-resolve it (history questions aren't in the arm state). trigger_answer on each
    ScoreTransition holds the whole batch joined into one string (keeps the field a plain
    str so the Trace Viewer renders unchanged; a single-answer submit has no per-answer
    attribution to lose anyway).
    """
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}

    new_answers: list[AnsweredQuestion] = []
    for question_id, answer_text in answers:
        if is_history_question_id(question_id):
            question_text = _find_history_question_text(history_checklist, question_id)
            history_answers.append(
                HistoryAnswer(
                    id=question_id,
                    question_text=question_text,
                    answer_text=answer_text,
                )
            )
        else:
            question = _find_question(current_triage, question_id)
            if question is None:
                raise ValueError(
                    f"question_id '{question_id}' not found in the current triage state."
                )
            question.answered = True
            question.answer_text = answer_text
            question_text = question.text

        new_answers.append(
            AnsweredQuestion(
                question_id=question_id,
                answer_text=answer_text,
                question_text=question_text,
            )
        )

    trigger = RescoreTrigger(new_answers=new_answers, current_arms=current_triage.arms)
    updated_triage = await rescore_arms(
        trigger,
        chief_complaint=current_triage.chief_complaint,
        red_flag_arm_names=red_flag_arm_names,
        history_answers=history_answers,
    )

    batch_answer_text = "; ".join(a.answer_text for a in new_answers)
    old_scores = {arm.name: arm.relevance_score for arm in current_triage.arms}
    transitions = [
        ScoreTransition(
            arm_name=arm.name,
            old_score=old_scores[arm.name],
            new_score=arm.relevance_score,
            trigger_answer=batch_answer_text,
        )
        for arm in updated_triage.arms
        if arm.name in old_scores and old_scores[arm.name] != arm.relevance_score
    ]
    return updated_triage, transitions


async def promote_newly_qualified(
    prev_triage: TriageOutput,
    updated_triage: TriageOutput,
    patient_context: str,
) -> None:
    """Old step 5: after a re-score, any arm NEWLY in the auto-generate top N that still
    has no questions gets them generated now (mutates `updated_triage` arms in place).

    Factored out so the streaming endpoint can run it AFTER emitting `rescored` and
    BEFORE ranking suggestions — the suggestion pool must see the promoted arms'
    questions. We compare top-N membership by NAME (scores can tie; names are stable)
    between the pre-rescore state and the merged state.
    """
    old_top = {arm.name for arm in _qualifying_arms(prev_triage)}
    newly_promoted = [
        arm
        for arm in _qualifying_arms(updated_triage)
        if arm.name not in old_top and not arm.questions
    ]
    if newly_promoted:
        await asyncio.gather(
            *(
                ensure_arm_questions(arm, updated_triage.chief_complaint, patient_context)
                for arm in newly_promoted
            )
        )


async def process_answers(
    answers: list[tuple[str, str]],
    current_triage: TriageOutput,
    patient_context: str,
    framework: Framework,
    history_checklist: HistoryChecklist | None = None,
    history_answers: list[HistoryAnswer] | None = None,
) -> tuple[TriageOutput, list[ScoreTransition], SuggestionBatch]:
    """Apply a BATCH of answers, re-score ONCE, and rank suggestions — the plain
    (non-streaming) composition.

    This is the card-level submit semantics: a whole card costs exactly one
    Prioritization call regardless of how many questions were answered; a single-answer
    submit is just a one-element batch. Returns the updated `TriageOutput`, the
    `ScoreTransition` records, AND the re-ranked `SuggestionBatch`.

    It now COMPOSES the three reusable steps (`apply_batch_and_rescore` ->
    `promote_newly_qualified` -> `build_suggestions`) that the streaming /api/answers
    endpoint drives one-by-one with stage events in between — so the streaming and
    plain paths share identical logic and can't drift. The plain path is still used by
    the single-answer /api/answer route and the terminal pipeline runner.
    """
    if history_answers is None:
        history_answers = []

    updated_triage, transitions = await apply_batch_and_rescore(
        answers, current_triage, framework, history_checklist, history_answers
    )
    await promote_newly_qualified(current_triage, updated_triage, patient_context)
    suggestions = await build_suggestions(
        updated_triage, framework, history_checklist, history_answers, transitions
    )
    return updated_triage, transitions, suggestions


# --- Clinician-added custom arms (POST /api/arm/custom) -----------------------------
#
# A custom-arm addition is, from the rest of the system's perspective, a re-score event:
# the differential CHANGED (new arms appended) rather than new evidence arriving, so it
# reuses the same `rescore_arms` + `build_suggestions` + transition-diff machinery the
# answer path uses. The ONE new piece is the validation/normalization of clinician-typed
# names; everything else is composition of existing, already-trusted functions.


def _arm_name_keys(name: str) -> set[str]:
    """The set of normalized comparison keys for an arm name, used for duplicate
    detection. Each key is lowercased and whitespace-collapsed. The set is:

      - the whole name,
      - the name with any parenthetical groups removed (the "outside" name), and
      - each parenthetical group's contents, further split on '/' and ',' .

    So "Deep Vein Thrombosis (DVT)" -> {"deep vein thrombosis (dvt)",
    "deep vein thrombosis", "dvt"} and "Cardiac (ACS / Ischemic)" -> {"cardiac (acs /
    ischemic)", "cardiac", "acs", "ischemic"}. Two names are treated as duplicates when
    their key sets intersect — this is what lets a short alias the clinician types ("DVT")
    match an existing canonical arm name ("Deep Vein Thrombosis (DVT)"). The rule is
    deliberately CONSERVATIVE (it only catches exact-key overlap, not fuzzy similarity):
    it will catch parenthetical-abbreviation aliases and case/spacing differences, but it
    will NOT, by design, flag merely-related distinct diagnoses (e.g. "Pancreatitis" vs
    "Acute Pancreatitis (AP)") as duplicates.
    """
    collapsed = " ".join(name.split()).lower()
    keys = {collapsed}
    for group in re.findall(r"\(([^)]*)\)", collapsed):
        for token in re.split(r"[/,]", group):
            token = " ".join(token.split())
            if token:
                keys.add(token)
    outside = " ".join(re.sub(r"\([^)]*\)", " ", collapsed).split())
    if outside:
        keys.add(outside)
    keys.discard("")
    return keys


def validate_custom_arm_names(
    arm_names: list[str], current_triage: TriageOutput
) -> list[str]:
    """Read-only pre-flight for POST /api/arm/custom. Cleans and validates the clinician-
    typed diagnosis names, raising ValueError (-> HTTP 400) on the FIRST problem and
    returning the cleaned (trimmed, internal-whitespace-collapsed, original-casing) names
    on success — the same fail-fast discipline as `validate_answer_ids`.

    Rejects: an empty list; any empty/whitespace-only name; a name that duplicates an
    EXISTING arm (by normalized key overlap — see `_arm_name_keys`, so "DVT" is rejected
    when "Deep Vein Thrombosis (DVT)" already exists); and duplicates WITHIN the submitted
    batch by the same rule. Pure and side-effect-free (it does not mutate the triage).
    """
    if not arm_names:
        raise ValueError("Provide at least one diagnosis name to add.")

    existing_keys: set[str] = set()
    for arm in current_triage.arms:
        existing_keys |= _arm_name_keys(arm.name)

    cleaned: list[str] = []
    batch_keys: set[str] = set()
    for raw in arm_names:
        name = " ".join(raw.split())  # trim + collapse internal whitespace, keep casing
        if not name:
            raise ValueError("Diagnosis names cannot be empty or whitespace only.")
        keys = _arm_name_keys(name)
        if keys & existing_keys:
            raise ValueError(
                f"A diagnosis matching '{name}' is already in the differential."
            )
        if keys & batch_keys:
            raise ValueError(f"Duplicate diagnosis '{name}' in the submitted list.")
        batch_keys |= keys
        cleaned.append(name)
    return cleaned


async def add_custom_arms(
    arm_names: list[str],
    current_triage: TriageOutput,
    patient_context: str,
) -> list[DiagnosticArm]:
    """Append clinician-named arms to `current_triage` and generate each one's question
    set concurrently — but do NOT score them here. Returns the new arms.

    The placeholder `relevance_score`/`reasoning` are TRANSIENT: the caller's very next
    step (`rescore_for_added_arms`) overwrites them with a real, case-specific score. The
    placeholder 0.5 is deliberately neutral (not 0 or 1) so that if a re-score somehow
    failed before reaching this arm, the leftover value reads as "unevaluated", not as a
    real high/low likelihood. Questions are generated via the SAME `ensure_arm_questions`
    primitive the expand route uses (concurrently, the same `asyncio.gather` fan-out
    pattern as the initial population) — there is no second question-generation path.

    Mutates `current_triage.arms` in place by appending all new arms BEFORE any scoring,
    which is exactly what makes "added together -> scored together" automatic: they are
    all present in the arm list the single `rescore_arms` call reasons over.
    """
    new_arms = [
        DiagnosticArm(
            name=name,
            relevance_score=0.5,  # transient placeholder; overwritten by the re-score
            reasoning="Newly added — pending evaluation.",  # transient; overwritten
            status="active",
            source="clinician",
            questions=[],
        )
        for name in arm_names
    ]
    current_triage.arms.extend(new_arms)
    await asyncio.gather(
        *(
            ensure_arm_questions(arm, current_triage.chief_complaint, patient_context)
            for arm in new_arms
        )
    )
    return new_arms


async def rescore_for_added_arms(
    new_arm_names: list[str],
    old_scores: dict[str, float],
    current_triage: TriageOutput,
    framework: Framework,
    history_answers: list[HistoryAnswer],
) -> tuple[TriageOutput, list[ScoreTransition]]:
    """Re-score EVERY arm jointly after custom arms were added, and diff against the
    pre-addition scores. The new arms already live in `current_triage.arms` (the caller
    appended them via `add_custom_arms`), so `rescore_arms`' existing joint reasoning
    scores them together with — and against — the existing differential, with zero
    special-casing. The trigger carries no new answers, only `newly_added_arm_names`, so
    the Prioritization Agent's system prompt explains these arms are freshly introduced.

    `old_scores` must be captured BEFORE the new arms were appended: a brand-new arm has
    no meaningful "old" score, so only PRE-EXISTING arms can produce a ScoreTransition
    (the new arms simply appear in the differential with their first real score). The
    diff logic mirrors `apply_batch_and_rescore`'s exactly.
    """
    red_flag_arm_names = {arm.name for arm in framework.arms if arm.red_flag}
    trigger = RescoreTrigger(
        new_answers=[],
        newly_added_arm_names=new_arm_names,
        current_arms=current_triage.arms,
    )
    updated_triage = await rescore_arms(
        trigger,
        chief_complaint=current_triage.chief_complaint,
        red_flag_arm_names=red_flag_arm_names,
        history_answers=history_answers,
    )

    trigger_text = "Added: " + ", ".join(new_arm_names)
    transitions = [
        ScoreTransition(
            arm_name=arm.name,
            old_score=old_scores[arm.name],
            new_score=arm.relevance_score,
            trigger_answer=trigger_text,
        )
        for arm in updated_triage.arms
        if arm.name in old_scores and old_scores[arm.name] != arm.relevance_score
    ]
    return updated_triage, transitions
