"""Pydantic data contracts between agents (CLAUDE.md Section 7).

Everything is re-exported here so other modules import from the package root —
`from app.models import DiagnosticArm` — rather than reaching into submodules.
This keeps the contract surface stable even if the internal file split changes.
"""

from app.models.clinical import ClinicalQuestion, DiagnosticArm
from app.models.triage import RescoreTrigger, TriageOutput
from app.models.trace import ScoreTransition

__all__ = [
    "ClinicalQuestion",
    "DiagnosticArm",
    "TriageOutput",
    "RescoreTrigger",
    "ScoreTransition",
]
