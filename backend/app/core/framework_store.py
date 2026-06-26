"""framework_store — the single abstracted entry point for framework persistence.

Same spirit as `call_agent.py` being the ONE entry point for AI calls: no other
module touches this database directly. Everything that needs to read or write a
cached framework goes through the three functions below, so the storage details
(SQLite today, maybe something else later) stay behind one seam.

Scope is deliberately small. This is a dumb key-value store: complaint string ->
serialized `Framework`. It does NOT do semantic matching ("does 'cephalgia' mean
'headache'?") — that is the Framework Agent's job (see `agents/framework_tools.py`).
This layer only canonicalizes the key (lowercase + trim) so trivially-different
spellings of the SAME words ("Chest Pain " vs "chest pain") don't create duplicate
rows; anything beyond that is not this layer's concern.

Connection policy: a fresh `sqlite3.connect()` per call, no pooling. This mirrors
`call_agent.py`'s "a fresh AsyncClient per call is fine for this phase"
justification — at MVP scale (a handful of complaints, low write frequency) pooling
is complexity with no payoff. The upgrade path, if it ever matters, plugs in here
without touching callers.
"""

import sqlite3
from pathlib import Path

from app.models import Framework

# backend/app/core/framework_store.py -> backend/app/data/frameworks.db.
# The data/ directory holds runtime-generated state (the cache), NOT source — it is
# gitignored. We create it on demand so a fresh checkout works with no setup step.
_DATA_DIR = Path(__file__).parent.parent / "data"
_DB_PATH = _DATA_DIR / "frameworks.db"


def _canonical(complaint: str) -> str:
    """Canonicalize a complaint into its cache key: lowercased and trimmed.

    This is NOT semantic matching — it only collapses whitespace/case noise so the
    same words don't land in two rows. Semantic equivalence ("cephalgia" ==
    "headache") is resolved upstream by the Framework Agent before we ever get here.
    """
    return complaint.strip().lower()


def _connect() -> sqlite3.Connection:
    """Open a connection, ensuring the data directory and table exist first.

    `CREATE TABLE IF NOT EXISTS` runs on every connect: it is a no-op once the table
    exists, and it means there is no separate migration/bootstrap step to remember —
    the first call from a clean checkout just works. (No migration tooling is
    warranted at this scope: one table, no schema evolution planned.)
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS frameworks (
            complaint  TEXT PRIMARY KEY,
            arms_json  TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def get_all_complaints() -> list[str]:
    """Return every canonical complaint string currently cached.

    Used by the semantic-match step to compare a new complaint against what already
    exists. Deliberately cheap: it SELECTs only the key column and never deserializes
    `arms_json` for rows that won't be returned — the matcher only needs the names.
    """
    conn = _connect()
    try:
        rows = conn.execute("SELECT complaint FROM frameworks").fetchall()
    finally:
        conn.close()
    return [row["complaint"] for row in rows]


def get_framework(complaint: str) -> Framework | None:
    """Load and validate the cached framework for a complaint key, or None if absent.

    Raises if the stored JSON fails `Framework` validation — a corrupt row should
    fail loud (same fail-loud-on-bad-shape principle as `call_agent`), not silently
    masquerade as a cache miss and trigger a needless regeneration.
    """
    key = _canonical(complaint)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT arms_json FROM frameworks WHERE complaint = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    # model_validate_json raises on a bad shape — we deliberately do NOT catch it.
    return Framework.model_validate_json(row["arms_json"])


def save_framework(complaint: str, framework: Framework) -> None:
    """Persist a framework under the given complaint key, overwriting any existing row.

    Uses INSERT ... ON CONFLICT so it is idempotent: re-saving the same complaint
    overwrites rather than erroring. This matters because two concurrent first-time
    requests for the SAME new complaint could both miss the cache and both generate —
    "last write wins" is the correct, crash-free resolution for that race (both
    generations are valid; we just keep one). `created_at` is left untouched on
    update, so it preserves the original first-seen time.
    """
    key = _canonical(complaint)
    payload = framework.model_dump_json()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO frameworks (complaint, arms_json)
            VALUES (?, ?)
            ON CONFLICT(complaint) DO UPDATE SET arms_json = excluded.arms_json
            """,
            (key, payload),
        )
        conn.commit()
    finally:
        conn.close()
