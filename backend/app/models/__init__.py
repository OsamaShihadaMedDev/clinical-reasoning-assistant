"""Pydantic data contracts between agents (CLAUDE.md Section 7).

Everything is re-exported here so other modules import from the package root —
`from app.models import DiagnosticArm` — rather than reaching into submodules.
This keeps the contract surface stable even if the internal file split changes.
"""

from app.models.clinical import ClinicalQuestion, DiagnosticArm
from app.models.framework import Framework, FrameworkArm
from app.models.history import (
    HISTORY_QUESTION_ID_PREFIX,
    HistoryAnswer,
    HistoryChecklist,
    HistoryQuestion,
    PatientCategory,
    is_history_question_id,
)
from app.models.suggestion import SuggestedQuestion, SuggestionBatch
from app.models.triage import AnsweredQuestion, RescoreTrigger, TriageOutput
from app.models.trace import ScoreTransition

__all__ = [
    "AnsweredQuestion",
    "ClinicalQuestion",
    "DiagnosticArm",
    "Framework",
    "FrameworkArm",
    "HISTORY_QUESTION_ID_PREFIX",
    "HistoryAnswer",
    "HistoryChecklist",
    "HistoryQuestion",
    "PatientCategory",
    "is_history_question_id",
    "SuggestedQuestion",
    "SuggestionBatch",
    "TriageOutput",
    "RescoreTrigger",
    "ScoreTransition",
]
