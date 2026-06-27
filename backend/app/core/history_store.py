"""history_store — the single abstracted entry point for general-history checklist
persistence. Same role for the History Agent that framework_store plays for the
Framework Agent: no other module touches this table directly.

It reuses the SAME SQLite file as framework_store (`data/frameworks.db`) but a
SEPARATE table (`history_checklists`). One file is one fewer thing to manage; the
separate table is non-negotiable, because the two have different primary keys
(`category` vs `complaint`) and different growth expectations — this table should
stabilize at exactly len(PatientCategory) rows forever, while `frameworks` keeps
growing as new complaints appear. Merging them would conflate "what population" with
"what complaint," the exact boundary the History/Framework split exists to keep.

IMPORTANT — what is cached vs what is not: only `category` + `questions` are stored
here. `assumed_default` and `category_reasoning` (on HistoryChecklist) describe how
ONE specific classification arrived at this category — they are NOT properties of the
reusable checklist content, so persisting them would pollute every future load. The
History Agent assembles the full HistoryChecklist AFTER this lookup, setting those two
fields from that call's own classification result.
"""

import json
import sqlite3
from pathlib import Path

from app.models import HistoryQuestion, PatientCategory

# Intentionally the SAME database file as framework_store (see module docstring),
# just a different table. app/core/history_store.py -> app/data/frameworks.db.
_DATA_DIR = Path(__file__).parent.parent / "data"
_DB_PATH = _DATA_DIR / "frameworks.db"


def _connect() -> sqlite3.Connection:
    """Open a connection, ensuring the data dir and the history table exist first.

    `CREATE TABLE IF NOT EXISTS` on every connect is a no-op once created and removes
    any separate bootstrap step — same approach as framework_store. This creates only
    the `history_checklists` table; the `frameworks` table is framework_store's to
    manage, even though both live in this one file.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_checklists (
            category       TEXT PRIMARY KEY,
            checklist_json TEXT NOT NULL,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def get_checklist(category: PatientCategory) -> list[HistoryQuestion] | None:
    """Load the cached questions for a category, or None if not yet generated.

    Returns ONLY the questions (not a full HistoryChecklist) by design — the agent
    layers assumed_default/category_reasoning on top from the live classification, so
    those are never read back from cache. Raises if the stored JSON fails validation
    (corrupt row fails loud, same as framework_store) rather than masquerading as a
    cache miss and triggering a needless regeneration.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT checklist_json FROM history_checklists WHERE category = ?",
            (category.value,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    # Deliberately not wrapped in try/except — a bad shape should raise loudly.
    raw = json.loads(row["checklist_json"])
    return [HistoryQuestion.model_validate(q) for q in raw["questions"]]


def save_checklist(category: PatientCategory, questions: list[HistoryQuestion]) -> None:
    """Persist the questions for a category, overwriting any existing row.

    INSERT ... ON CONFLICT for idempotency, same reasoning as
    framework_store.save_framework: two concurrent first-time generations for the same
    category should resolve to last-write-wins, not crash. Stores only category +
    questions (see module docstring); created_at is preserved on update.
    """
    payload = json.dumps({"questions": [q.model_dump() for q in questions]})
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO history_checklists (category, checklist_json)
            VALUES (?, ?)
            ON CONFLICT(category) DO UPDATE SET checklist_json = excluded.checklist_json
            """,
            (category.value, payload),
        )
        conn.commit()
    finally:
        conn.close()
