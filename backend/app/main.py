"""FastAPI app — the first HTTP surface over the working agent pipeline.

This exposes the already-built, already-verified pipeline functions (`run_triage`,
`populate_questions`, `process_answer`) over two routes, plus serves a throwaway
plain-HTML demo page so the whole feedback loop can be driven in a browser by a human
typing real answers. No SSE yet (CLAUDE.md Section 12 puts streaming after this), no
React yet — the demo page is scaffolding, not the real frontend.
"""

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agents.triage import run_triage
from app.core.orchestration import populate_questions
from app.core.rescore import process_answer
from app.models import ScoreTransition, TriageOutput

app = FastAPI(title="Clinical Reasoning Assistant")

_STATIC_DIR = Path(__file__).parent / "static"

# In-memory session store. CLAUDE.md Section 7: session state is intentionally the
# simplest possible thing for the MVP — a plain module-level dict, no Redis, no DB.
# It keys an ongoing interview's current TriageOutput by a generated session id so a
# follow-up /api/answer call can re-score the SAME interview. This resets if the
# server restarts and isn't multi-process safe — both fine for a local single-user
# demo, and the documented upgrade path (Redis) plugs in here without touching the
# agents.
_SESSIONS: dict[str, TriageOutput] = {}


class TriageRequest(BaseModel):
    chief_complaint: str
    patient_context: str


class TriageResponse(BaseModel):
    session_id: str
    triage: TriageOutput


class AnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer_text: str


class AnswerResponse(BaseModel):
    triage: TriageOutput
    transitions: list[ScoreTransition]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/demo.html")
def demo_page() -> FileResponse:
    """Serve the throwaway demo page at a clean, top-level URL. A FileResponse route
    (rather than a StaticFiles mount) keeps the page same-origin with /api/* so no
    CORS setup is needed, and avoids a catch-all mount shadowing the API routes."""
    return FileResponse(_STATIC_DIR / "demo.html")


@app.post("/api/triage", response_model=TriageResponse)
async def start_triage(request: TriageRequest) -> TriageResponse:
    """Start an interview: score the arms, then generate questions for active arms —
    exactly what the terminal pipeline runner does — and stash the result in the
    session store so it can be re-scored later."""
    triage = await run_triage(request.chief_complaint, request.patient_context)
    triage = await populate_questions(
        triage, request.chief_complaint, request.patient_context
    )

    session_id = uuid4().hex
    _SESSIONS[session_id] = triage
    return TriageResponse(session_id=session_id, triage=triage)


@app.post("/api/answer", response_model=AnswerResponse)
async def answer_question(request: AnswerRequest) -> AnswerResponse:
    """Record one answer against an ongoing interview and re-score. Returns the
    updated state AND the ScoreTransition records for THIS answer (what the trace log
    renders)."""
    current = _SESSIONS.get(request.session_id)
    if current is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active session '{request.session_id}'. Start a new interview "
                f"via POST /api/triage first (sessions are in-memory and reset when "
                f"the server restarts)."
            ),
        )

    # process_answer raises ValueError if the question id isn't in this session's
    # arms. Surface that as a clear 400 rather than an opaque 500.
    try:
        updated, transitions = await process_answer(
            request.question_id, request.answer_text, current
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _SESSIONS[request.session_id] = updated
    return AnswerResponse(triage=updated, transitions=transitions)
