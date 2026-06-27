"""FastAPI app — the HTTP surface over the working agent pipeline.

This exposes the already-built, already-verified pipeline functions (`run_triage`,
`populate_questions`, `process_answers`) over HTTP, plus serves a throwaway plain-HTML
demo page so the whole feedback loop can be driven in a browser by a human typing real
answers. The demo page is scaffolding, not the real (React) frontend.

Triage has TWO routes: a one-shot `POST /api/triage` (kept for tests/scripts that want
a single response) and a streaming `GET /api/triage/stream` (SSE) that reveals arm
cards progressively as each agent finishes. `POST /api/answer` is deliberately NOT
streamed: re-scoring is a SINGLE combined agent call (CLAUDE.md Section 7), so there's
no multi-step progressive reveal to stream — it returns one result in one shot.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.agents.framework_agent import resolve_framework
from app.agents.history_agent import resolve_history_checklist
from app.agents.triage import run_triage
from app.core.orchestration import (
    ensure_arm_questions,
    populate_questions,
    populate_questions_streaming,
)
from app.core.rescore import build_suggestions, process_answers
from app.models import (
    DiagnosticArm,
    Framework,
    HistoryAnswer,
    HistoryChecklist,
    ScoreTransition,
    SuggestionBatch,
    TriageOutput,
)

app = FastAPI(title="Clinical Reasoning Assistant")

_STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class _Session:
    """Everything one ongoing interview needs to keep on the server.

    Was just a bare `TriageOutput`, but lazy question generation (top-N auto-generate)
    means a later /api/answer or /api/arm/expand call may need to generate questions
    for an arm that had none — and to keep those tailored to the SAME patient the
    initial fan-out saw, we must remember the `patient_context`. TriageOutput only
    carries the chief_complaint, so the patient context is stored alongside it here.

    `framework` (the diagnostic-arm framework resolved for this complaint) is also kept
    because re-scoring needs this session's red-flag arm names, which live on the
    framework and NOT on TriageOutput/DiagnosticArm. Stashing it once at session start
    avoids re-resolving (and possibly re-generating) the framework on every answer.

    `history_checklist` (the general-history checklist resolved for this patient's
    population) is kept so /api/answer can look up a general-history question's text by
    id when one is answered. `history_answers` accumulates the answered general-history
    items across the session; the Prioritization Agent reads it as background context on
    every re-score (Step 8).

    `suggestions` is the latest clinician-facing "what to ask next" pool (Suggestion
    Agent). Defaulted to empty so a session can exist before one is computed: the SSE
    triage path does NOT compute it yet (deferred to the SSE-suggestions follow-up), but
    the very first /api/answers re-score recomputes it for that session regardless.
    """

    triage: TriageOutput
    patient_context: str
    framework: Framework
    history_checklist: HistoryChecklist
    history_answers: list[HistoryAnswer] = field(default_factory=list)
    suggestions: SuggestionBatch = field(
        default_factory=lambda: SuggestionBatch(suggestions=[])
    )


# In-memory session store. CLAUDE.md Section 7: session state is intentionally the
# simplest possible thing for the MVP — a plain module-level dict, no Redis, no DB.
# It keys an ongoing interview's state by a generated session id so a follow-up
# /api/answer or /api/arm/expand call can act on the SAME interview. This resets if the
# server restarts and isn't multi-process safe — both fine for a local single-user
# demo, and the documented upgrade path (Redis) plugs in here without touching the
# agents.
_SESSIONS: dict[str, _Session] = {}


class TriageRequest(BaseModel):
    chief_complaint: str
    patient_context: str


class TriageResponse(BaseModel):
    session_id: str
    triage: TriageOutput
    # The general-history checklist for this patient's population, returned as its OWN
    # field (NOT merged into TriageOutput) so the frontend renders it as a separate
    # card above the diagnostic arms. The History Agent runs before triage.
    history: HistoryChecklist
    # The clinician-facing "what to ask next" pool, ranked at interview start (no score
    # momentum yet). NOTE: the live React frontend gets its initial state over SSE, not
    # this JSON route, so it does not consume this field yet — wiring suggestions onto
    # the SSE stream is the next prompt. Returned here so the JSON route is contract-
    # complete and testable via curl/demo.html now.
    suggestions: SuggestionBatch


class AnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer_text: str


class AnswerItem(BaseModel):
    """One (question_id, answer_text) pair within a card-level batch submission."""

    question_id: str
    answer_text: str


class AnswerBatchRequest(BaseModel):
    session_id: str
    answers: list[AnswerItem]


class AnswerResponse(BaseModel):
    triage: TriageOutput
    transitions: list[ScoreTransition]
    # The re-ranked "what to ask next" pool, recomputed on every re-score so it reflects
    # the just-applied answers and any newly-promoted arm. (This field the React frontend
    # WILL consume — /api/answers is plain JSON, not SSE.)
    suggestions: SuggestionBatch


class ArmExpandRequest(BaseModel):
    session_id: str
    arm_name: str


class ArmExpandResponse(BaseModel):
    arm: DiagnosticArm


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
    """Start an interview: resolve the general-history checklist (by patient
    population), then the complaint's framework, score the arms, generate questions for
    active arms, and stash everything in the session store so it can be re-scored later.

    Agent order: History Agent FIRST (classify population, load/generate the general-
    history checklist), THEN Framework Agent (load/generate the complaint framework),
    THEN triage + question generation. The history checklist is returned as its own
    response field and is independent of the complaint-specific arms."""
    history = await resolve_history_checklist(request.patient_context)
    framework = await resolve_framework(request.chief_complaint)
    triage = await run_triage(
        framework, request.chief_complaint, request.patient_context
    )
    triage = await populate_questions(
        triage, request.chief_complaint, request.patient_context
    )

    # Rank the initial suggestion pool so it's populated immediately at interview start,
    # not only after the first answer. No transitions yet (nothing has moved).
    suggestions = await build_suggestions(
        triage, framework, history, history_answers=[], transitions=[]
    )

    session_id = uuid4().hex
    _SESSIONS[session_id] = _Session(
        triage=triage,
        patient_context=request.patient_context,
        framework=framework,
        history_checklist=history,
        suggestions=suggestions,
    )
    return TriageResponse(
        session_id=session_id,
        triage=triage,
        history=history,
        suggestions=suggestions,
    )


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame: a named `event:` line, a single-line JSON
    `data:` line, and a blank line to terminate the frame. json.dumps emits no raw
    newlines, so one data line is always sufficient here."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _triage_event_stream(
    chief_complaint: str, patient_context: str
) -> AsyncIterator[str]:
    """The SSE body for GET /api/triage/stream.

    Emits, in order:
      0. `history`       — once the History Agent resolves the general-history checklist
                           (classify population, load/generate): the frontend renders the
                           General History card immediately, before any arms.
      1. `triage`        — once run_triage() returns: all arms scored, questions still
                           empty, so the frontend can render score cards immediately.
      2. `arm_questions` — one per qualifying arm, the moment that arm's questions land
                           (completion order, via populate_questions_streaming). Only
                           that arm's data is sent, not the whole triage object again.
      3. `done`          — once after every arm has streamed: carries the session_id,
                           and the now-fully-populated TriageOutput (plus the history
                           checklist) is stored in _SESSIONS so /api/answer can re-score
                           this same interview.

    Any failure (history, framework, triage, or a question-generation call) is surfaced
    as an `error` event with a JSON `detail`, then the stream ends — never an unhandled
    exception silently killing the connection.
    """
    # Stage 0/1: resolve the general-history checklist, then the framework, then triage
    # scoring. All inside this try so ANY resolution failure surfaces as a clean SSE
    # `error` event, not an unhandled exception silently killing the stream.
    try:
        history = await resolve_history_checklist(patient_context)
        yield _sse("history", history.model_dump(mode="json"))

        framework = await resolve_framework(chief_complaint)
        triage = await run_triage(framework, chief_complaint, patient_context)
    except Exception as exc:  # noqa: BLE001 — surface ANY failure to the client cleanly
        yield _sse("error", {"detail": f"Triage failed: {exc}"})
        return

    yield _sse("triage", triage.model_dump())

    # Stage 2: stream each arm's questions as it completes. The generator mutates
    # `triage` in place, so by the time it's exhausted `triage` is fully populated.
    try:
        async for arm, _questions in populate_questions_streaming(
            triage, chief_complaint, patient_context
        ):
            yield _sse(
                "arm_questions",
                {"name": arm.name, "questions": [q.model_dump() for q in arm.questions]},
            )
    except Exception as exc:  # noqa: BLE001 — same fail-loud-to-client contract
        yield _sse("error", {"detail": f"Question generation failed: {exc}"})
        return

    # Stage 3: persist the complete interview and hand back the session id.
    session_id = uuid4().hex
    _SESSIONS[session_id] = _Session(
        triage=triage,
        patient_context=patient_context,
        framework=framework,
        history_checklist=history,
    )
    yield _sse("done", {"session_id": session_id})


@app.get("/api/triage/stream")
async def stream_triage(
    chief_complaint: str, patient_context: str = ""
) -> StreamingResponse:
    """Streaming counterpart to POST /api/triage. GET with query params because the
    browser's EventSource can only issue a GET with no body. Same work as the one-shot
    route, but delivered progressively over SSE."""
    return StreamingResponse(
        _triage_event_stream(chief_complaint, patient_context),
        media_type="text/event-stream",
        # no-cache + disabling proxy buffering keeps events flushing immediately
        # rather than being held back and delivered as one batch.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _apply_answers(
    session_id: str, answers: list[tuple[str, str]]
) -> AnswerResponse:
    """Shared body for both answer routes: look up the session, run the ONE batch
    re-score, persist, and return. The single-answer route passes a one-item list; the
    batch route passes the whole card. Keeping ONE implementation here (rather than two
    parallel route bodies) is what makes the singular route a true thin wrapper and not
    a second code path that can drift."""
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active session '{session_id}'. Start a new interview "
                f"via POST /api/triage first (sessions are in-memory and reset when "
                f"the server restarts)."
            ),
        )

    # process_answers raises ValueError if any question id isn't found (in the arms for
    # an arm answer, or in the checklist for a history answer). Surface that as a clean
    # 400, not an opaque 500. patient_context is passed so a promotion into the top N
    # generates tailored questions; history_checklist/history_answers let general-history
    # answers be recorded and fed to the re-score as background context. NOTE:
    # process_answers appends history answers to session.history_answers IN PLACE, so the
    # session keeps them without us reassigning the list.
    try:
        updated, transitions, suggestions = await process_answers(
            answers,
            session.triage,
            session.patient_context,
            session.framework,
            history_checklist=session.history_checklist,
            history_answers=session.history_answers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _SESSIONS[session_id] = _Session(
        triage=updated,
        patient_context=session.patient_context,
        framework=session.framework,
        history_checklist=session.history_checklist,
        history_answers=session.history_answers,
        suggestions=suggestions,
    )
    return AnswerResponse(triage=updated, transitions=transitions, suggestions=suggestions)


@app.post("/api/answers", response_model=AnswerResponse)
async def answer_questions_batch(request: AnswerBatchRequest) -> AnswerResponse:
    """Record one or more answers from a SINGLE card submission and re-score ONCE.

    This is the primary answer route the React frontend uses: a card-level submit sends
    every newly-answered question in that card together, costing exactly one
    Prioritization call regardless of how many were answered, and letting the agent
    reason over them jointly. Answers may be arm questions or general-history questions
    (process_answers routes each by its id)."""
    return await _apply_answers(
        request.session_id,
        [(a.question_id, a.answer_text) for a in request.answers],
    )


@app.post("/api/answer", response_model=AnswerResponse)
async def answer_question(request: AnswerRequest) -> AnswerResponse:
    """Single-answer compatibility route — a thin one-item wrapper over the same batch
    machinery (`/api/answers`). Kept because the throwaway demo.html still posts one
    answer at a time here; the React frontend uses `/api/answers`. Not a parallel
    implementation — it delegates straight into `_apply_answers`."""
    return await _apply_answers(
        request.session_id, [(request.question_id, request.answer_text)]
    )


@app.post("/api/arm/expand", response_model=ArmExpandResponse)
async def expand_arm(request: ArmExpandRequest) -> ArmExpandResponse:
    """On-demand question generation for ONE arm the top-N fan-out skipped.

    With top-N auto-generate (config.TOP_N_AUTO_GENERATE), only the highest-scoring
    active arms get questions at triage time; the rest arrive with an empty list. When
    the user expands one of those arms in the UI, the frontend calls this to fill it in.

    Identified by arm_name in the JSON body rather than a URL path segment ON PURPOSE:
    arm names contain spaces, parentheses and slashes (e.g. "Cardiac (ACS / Ischemic)"),
    which are awkward/ambiguous in a path, and a JSON body matches the existing
    /api/answer convention (session_id + payload in the body).

    Idempotent: it delegates to `ensure_arm_questions`, which no-ops if the arm already
    has questions — so the frontend can call it defensively without first checking, and
    a double-click never regenerates or duplicates. Returns the arm's current state
    (questions included) either way.
    """
    session = _SESSIONS.get(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active session '{request.session_id}'. Start a new interview "
                f"via POST /api/triage first (sessions are in-memory and reset when "
                f"the server restarts)."
            ),
        )

    arm = next(
        (a for a in session.triage.arms if a.name == request.arm_name), None
    )
    if arm is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No arm named '{request.arm_name}' in session "
                f"'{request.session_id}'. Use the exact arm name from the triage "
                f"response."
            ),
        )

    # No-op if already populated; otherwise generates and mutates the arm in place
    # (so it's reflected in the stored session's TriageOutput).
    await ensure_arm_questions(
        arm, session.triage.chief_complaint, session.patient_context
    )
    _SESSIONS[request.session_id] = session  # arm mutated in place; re-store for clarity
    return ArmExpandResponse(arm=arm)
