/**
 * Thin transport layer over the FastAPI backend. Two calls, mirroring the two
 * routes the interview uses:
 *   - openTriageStream() — GET /api/triage/stream over SSE (EventSource), the
 *     progressive reveal: a `triage` event, then one `arm_questions` per arm, then
 *     `done` (or `error`). This is the same consumption shape demo.html proved.
 *   - submitAnswer()     — POST /api/answer, the re-scoring feedback call.
 *
 * Requests are same-origin (`/api/...`); Vite's dev proxy forwards them to the
 * FastAPI server, so no CORS handling is needed (see vite.config.ts).
 */

import type {
  AnswerResponse,
  ArmExpandResponse,
  ArmQuestionsEvent,
  ClinicalQuestion,
  HistoryChecklist,
  ScoreTransition,
  SuggestionBatch,
  TriageOutput,
} from "@/types"

export interface TriageStreamHandlers {
  /** General-history checklist resolved (fires before `triage`) — render the General
   *  History card immediately, above the arms. */
  onHistory: (checklist: HistoryChecklist) => void
  /** All arms scored (questions still empty) — render score cards immediately. */
  onTriage: (triage: TriageOutput) => void
  /** One arm's questions landed (completion order). */
  onArmQuestions: (name: string, questions: ClinicalQuestion[]) => void
  /** The ranked "what to ask next" pool (fires after all arms, before `done`). */
  onSuggestions: (suggestions: SuggestionBatch) => void
  /** Stream finished; carries the session id for follow-up /api/answers calls. */
  onDone: (sessionId: string) => void
  /** A server-sent `error` event, or the connection dropping before `done`. */
  onError: (detail: string) => void
}

/**
 * Open the triage SSE stream. Returns a cleanup function that closes the
 * EventSource — call it on unmount or to abort an in-flight stream.
 *
 * EventSource fires the generic `error` listener for BOTH a server-sent
 * `event: error` (which carries `.data`) and ordinary connection-level errors
 * (no `.data`, including the normal close right after `done`). We distinguish
 * them with a `completed` flag so a clean finish never surfaces a scary message —
 * exactly the disambiguation demo.html documents.
 */
export function openTriageStream(
  chiefComplaint: string,
  patientContext: string,
  handlers: TriageStreamHandlers,
): () => void {
  const url =
    "/api/triage/stream" +
    "?chief_complaint=" +
    encodeURIComponent(chiefComplaint) +
    "&patient_context=" +
    encodeURIComponent(patientContext)

  const es = new EventSource(url)
  let completed = false

  es.addEventListener("history", (ev) => {
    handlers.onHistory(JSON.parse(ev.data) as HistoryChecklist)
  })

  es.addEventListener("triage", (ev) => {
    handlers.onTriage(JSON.parse(ev.data) as TriageOutput)
  })

  es.addEventListener("arm_questions", (ev) => {
    const d = JSON.parse(ev.data) as ArmQuestionsEvent
    handlers.onArmQuestions(d.name, d.questions)
  })

  es.addEventListener("suggestions", (ev) => {
    handlers.onSuggestions(JSON.parse(ev.data) as SuggestionBatch)
  })

  es.addEventListener("done", (ev) => {
    completed = true
    const { session_id } = JSON.parse(ev.data) as { session_id: string }
    handlers.onDone(session_id)
    es.close()
  })

  es.addEventListener("error", (ev: MessageEvent) => {
    if (ev.data) {
      let detail = "stream error"
      try {
        detail = (JSON.parse(ev.data) as { detail?: string }).detail || detail
      } catch {
        /* keep fallback */
      }
      handlers.onError(detail)
    } else if (!completed) {
      handlers.onError("Connection to the stream was lost before completion.")
    }
    es.close()
  })

  return () => es.close()
}

/**
 * Pure SSE wire-format helpers (no network) so the answer stream's frame parsing is
 * testable in isolation and shared, not re-implemented inline. The wire format matches
 * the backend's `_sse()`: frames separated by a blank line (`\n\n`), each frame a
 * `event: <name>` line and a `data: <json>` line.
 */

/** Split a buffer into COMPLETE frames plus the trailing remainder (which may be a
 *  partial frame — a streamed read can fragment mid-frame, so the caller carries `rest`
 *  forward and re-feeds it with the next chunk). */
export function splitSSEFrames(buffer: string): { frames: string[]; rest: string } {
  const parts = buffer.split("\n\n")
  const rest = parts.pop() ?? "" // last piece is incomplete until the next `\n\n` arrives
  return { frames: parts.filter((f) => f.trim().length > 0), rest }
}

/** Parse one raw frame's `event:`/`data:` lines into a typed pair. Unknown lines are
 *  ignored; multiple `data:` lines join with newlines (SSE spec), though the backend
 *  only ever emits one. Defaults to event "message" if none given. */
export function parseSSEFrame(raw: string): { event: string; data: string } {
  let event = "message"
  const dataLines: string[] = []
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice("event:".length).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trim())
  }
  return { event, data: dataLines.join("\n") }
}

export interface AnswerStreamHandlers {
  /** Re-score started; `armCount` active arms are being weighed. */
  onRescoring: (armCount: number) => void
  /** Arms re-scored; transitions are ready (differential can update before suggestions). */
  onRescored: (transitions: ScoreTransition[]) => void
  /** Suggestion ranking started. */
  onRankingSuggestions: () => void
  /** Finished: the full AnswerResponse (same shape the old JSON body had). */
  onDone: (response: AnswerResponse) => void
  /** A pre-stream HTTP error (404/400) or a mid-stream `error` frame. */
  onError: (detail: string) => void
}

/**
 * POST /api/answers and consume its SSE stream. This is a POST (the batch needs a JSON
 * body), which `EventSource` can't do — so we read the `fetch` response body as a stream
 * and parse SSE frames manually with the helpers above. Stage events drive the staged
 * status UI; the `done` frame carries the same payload the old plain-JSON response did.
 *
 * Resolves when the stream ends (it does not throw on a backend error — errors are
 * delivered via `onError`, matching `openTriageStream`'s callback style).
 */
export async function streamAnswers(
  sessionId: string,
  answers: { question_id: string; answer_text: string }[],
  handlers: AnswerStreamHandlers,
): Promise<void> {
  const res = await fetch("/api/answers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, answers }),
  })

  // Pre-stream HTTP errors (404 missing session, 400 bad question_id) arrive as a normal
  // JSON error body, not an SSE frame — surface them the same way.
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      detail = ((await res.json()) as { detail?: string }).detail || detail
    } catch {
      /* keep fallback */
    }
    handlers.onError(detail)
    return
  }

  const dispatch = ({ event, data }: { event: string; data: string }) => {
    switch (event) {
      case "rescoring":
        handlers.onRescoring((JSON.parse(data) as { arm_count: number }).arm_count)
        break
      case "rescored":
        handlers.onRescored(
          (JSON.parse(data) as { transitions: ScoreTransition[] }).transitions,
        )
        break
      case "ranking_suggestions":
        handlers.onRankingSuggestions()
        break
      case "done":
        handlers.onDone(JSON.parse(data) as AnswerResponse)
        break
      case "error":
        handlers.onError(
          (JSON.parse(data) as { detail?: string }).detail || "stream error",
        )
        break
    }
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { frames, rest } = splitSSEFrames(buffer)
    buffer = rest
    for (const frame of frames) dispatch(parseSSEFrame(frame))
  }
  // Flush any final frame not terminated by a trailing blank line.
  const leftover = buffer.trim()
  if (leftover) dispatch(parseSSEFrame(leftover))
}

export interface CustomArmStreamHandlers {
  /** New arms accepted; their questions are being generated. Data: the names. */
  onAddingArms: (names: string[]) => void
  /** Re-score started; `armCount` active arms (incl. the new ones) are being weighed. */
  onRescoring: (armCount: number) => void
  /** Arms re-scored; transitions for the pre-existing arms that moved. */
  onRescored: (transitions: ScoreTransition[]) => void
  /** Suggestion ranking started. */
  onRankingSuggestions: () => void
  /** Finished: the full AnswerResponse (same shape the answer stream's `done` carries). */
  onDone: (response: AnswerResponse) => void
  /** A pre-stream HTTP error (404/400) or a mid-stream `error` frame. */
  onError: (detail: string) => void
}

/**
 * POST /api/arm/custom and consume its SSE stream — add one or more clinician-named
 * diagnostic arms, scored TOGETHER against the case-so-far. Adding a diagnosis is a
 * re-score event, so this mirrors `streamAnswers` exactly (POST + ReadableStream + the
 * shared SSE frame helpers); it just has one extra leading `adding_arms` stage and the
 * same `done` payload shape, so the hook reuses its answer-`done` handling.
 */
export async function streamCustomArms(
  sessionId: string,
  armNames: string[],
  handlers: CustomArmStreamHandlers,
): Promise<void> {
  const res = await fetch("/api/arm/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, arm_names: armNames }),
  })

  // Pre-stream HTTP errors (404 missing session, 400 empty/duplicate name) arrive as a
  // normal JSON error body, not an SSE frame — surface them the same way.
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      detail = ((await res.json()) as { detail?: string }).detail || detail
    } catch {
      /* keep fallback */
    }
    handlers.onError(detail)
    return
  }

  const dispatch = ({ event, data }: { event: string; data: string }) => {
    switch (event) {
      case "adding_arms":
        handlers.onAddingArms((JSON.parse(data) as { names: string[] }).names)
        break
      case "rescoring":
        handlers.onRescoring((JSON.parse(data) as { arm_count: number }).arm_count)
        break
      case "rescored":
        handlers.onRescored(
          (JSON.parse(data) as { transitions: ScoreTransition[] }).transitions,
        )
        break
      case "ranking_suggestions":
        handlers.onRankingSuggestions()
        break
      case "done":
        handlers.onDone(JSON.parse(data) as AnswerResponse)
        break
      case "error":
        handlers.onError(
          (JSON.parse(data) as { detail?: string }).detail || "stream error",
        )
        break
    }
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { frames, rest } = splitSSEFrames(buffer)
    buffer = rest
    for (const frame of frames) dispatch(parseSSEFrame(frame))
  }
  const leftover = buffer.trim()
  if (leftover) dispatch(parseSSEFrame(leftover))
}

/** POST /api/arm/expand — lazily generate questions for ONE arm the top-N fan-out
 *  skipped. Idempotent server-side: an already-populated arm comes back unchanged
 *  (no regeneration), so the UI can call this whenever a question-less arm opens
 *  without first checking. Throws Error(detail) on a non-2xx, like submitAnswer. */
export async function expandArm(
  sessionId: string,
  armName: string,
): Promise<ArmExpandResponse> {
  const res = await fetch("/api/arm/expand", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, arm_name: armName }),
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = ((await res.json()) as { detail?: string }).detail || detail
    } catch {
      /* keep fallback */
    }
    throw new Error(detail)
  }

  return (await res.json()) as ArmExpandResponse
}
