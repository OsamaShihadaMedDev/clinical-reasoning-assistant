"""Unit tests for the Suggestion Agent's pure merge step (_merge_suggestions).

This is the deterministic, NO-AI half of the Suggestion Agent: given the model's raw
output plus the real candidate pool, it validates ids, copies authoritative text, and
computes is_history_question / is_red_flag / source_arms in code. Exactly the
"don't trust the model on identity/safety" logic worth pinning down with a test.

The project has no pytest dependency, so this doubles as a plain script: run it with

    PYTHONPATH=. uv run python tests/test_suggestion_merge.py

(from backend/), and it will execute every test_* function and print a summary. It is
also pytest-compatible (test_* functions, plain asserts) if pytest is added later.
"""

from app.agents.suggestion_agent import _merge_suggestions
from app.models import SuggestedQuestion, SuggestionBatch

# A candidate pool: id -> (question_text, home_arm | None). One arm question, one
# general-history question (None home arm).
_POOL = {
    "cardiac-acs-ischemic-1": (
        "Do you get the chest pain on exertion?",
        "Cardiac (ACS / Ischemic)",
    ),
    "histq-adult_general-3": ("Do you smoke?", None),
}
_VALID_ARM_NAMES = {"Cardiac (ACS / Ischemic)", "GERD / Esophageal"}
_RED_FLAG_ARM_NAMES = {"Cardiac (ACS / Ischemic)"}


def test_drops_bogus_and_flags_in_code() -> None:
    """One valid arm id, one bogus id, one history id — the bogus one is dropped, and
    the code-computed flags/text override whatever the model emitted."""
    raw = SuggestionBatch(
        suggestions=[
            # Valid arm question. The model echoed the WRONG text, named a non-existent
            # arm, and (wrongly) said is_red_flag=False — all must be corrected in code.
            SuggestedQuestion(
                question_id="cardiac-acs-ischemic-1",
                question_text="WRONG ECHOED TEXT",
                source_arms=["Cardiac (ACS / Ischemic)", "Nonexistent Arm"],
                justification="  exertional angina screen  ",
                is_red_flag=False,
                is_history_question=False,
            ),
            # Bogus id not in the pool — must be dropped entirely.
            SuggestedQuestion(
                question_id="totally-made-up-99",
                question_text="invented",
                source_arms=[],
                justification="should be dropped",
                is_red_flag=True,
                is_history_question=False,
            ),
            # History question. The model wrongly attached an arm and wrong booleans.
            SuggestedQuestion(
                question_id="histq-adult_general-3",
                question_text="echo",
                source_arms=["Cardiac (ACS / Ischemic)"],
                justification="smoking history",
                is_red_flag=True,
                is_history_question=False,
            ),
        ]
    )

    out = _merge_suggestions(
        raw, _POOL, _VALID_ARM_NAMES, _RED_FLAG_ARM_NAMES, pool_size=4
    )

    # Bogus dropped -> exactly two remain, order preserved.
    assert [s.question_id for s in out.suggestions] == [
        "cardiac-acs-ischemic-1",
        "histq-adult_general-3",
    ]

    arm = out.suggestions[0]
    assert arm.question_text == "Do you get the chest pain on exertion?"  # from pool
    assert arm.source_arms == ["Cardiac (ACS / Ischemic)"]  # bogus arm dropped, home kept
    assert arm.is_red_flag is True  # computed: home arm is a red-flag arm
    assert arm.is_history_question is False
    assert arm.justification == "exertional angina screen"  # stripped

    hist = out.suggestions[1]
    assert hist.question_text == "Do you smoke?"  # from pool
    assert hist.source_arms == []  # history questions carry no arms, model's ignored
    assert hist.is_red_flag is False  # no source arms -> not red-flag
    assert hist.is_history_question is True  # computed from the histq- id prefix


def test_truncates_to_pool_size() -> None:
    """If the model returns more than pool_size valid ids, the merge truncates."""
    raw = SuggestionBatch(
        suggestions=[
            SuggestedQuestion(
                question_id="cardiac-acs-ischemic-1",
                question_text="x",
                source_arms=[],
                justification="a",
                is_red_flag=False,
                is_history_question=False,
            ),
            SuggestedQuestion(
                question_id="histq-adult_general-3",
                question_text="y",
                source_arms=[],
                justification="b",
                is_red_flag=False,
                is_history_question=False,
            ),
        ]
    )
    out = _merge_suggestions(
        raw, _POOL, _VALID_ARM_NAMES, _RED_FLAG_ARM_NAMES, pool_size=1
    )
    assert len(out.suggestions) == 1
    assert out.suggestions[0].question_id == "cardiac-acs-ischemic-1"


def test_dedups_repeated_id() -> None:
    """A repeated id keeps only the first (higher-ranked) occurrence."""
    raw = SuggestionBatch(
        suggestions=[
            SuggestedQuestion(
                question_id="cardiac-acs-ischemic-1",
                question_text="x",
                source_arms=[],
                justification="first",
                is_red_flag=False,
                is_history_question=False,
            ),
            SuggestedQuestion(
                question_id="cardiac-acs-ischemic-1",
                question_text="x",
                source_arms=[],
                justification="duplicate",
                is_red_flag=False,
                is_history_question=False,
            ),
        ]
    )
    out = _merge_suggestions(
        raw, _POOL, _VALID_ARM_NAMES, _RED_FLAG_ARM_NAMES, pool_size=4
    )
    assert len(out.suggestions) == 1
    assert out.suggestions[0].justification == "first"


if __name__ == "__main__":
    tests = [
        test_drops_bogus_and_flags_in_code,
        test_truncates_to_pool_size,
        test_dedups_repeated_id,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"\nAll {len(tests)} suggestion-merge tests passed.")
