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
  TriageOutput,
} from "@/types"

export interface TriageStreamHandlers {
  /** All arms scored (questions still empty) — render score cards immediately. */
  onTriage: (triage: TriageOutput) => void
  /** One arm's questions landed (completion order). */
  onArmQuestions: (name: string, questions: ClinicalQuestion[]) => void
  /** Stream finished; carries the session id for follow-up /api/answer calls. */
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

  es.addEventListener("triage", (ev) => {
    handlers.onTriage(JSON.parse(ev.data) as TriageOutput)
  })

  es.addEventListener("arm_questions", (ev) => {
    const d = JSON.parse(ev.data) as ArmQuestionsEvent
    handlers.onArmQuestions(d.name, d.questions)
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

/** POST /api/answer — record one answer and re-score. Throws Error(detail) on a
 *  non-2xx so callers can surface the backend's clean 400/404 message. */
export async function submitAnswer(
  sessionId: string,
  questionId: string,
  answerText: string,
): Promise<AnswerResponse> {
  const res = await fetch("/api/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
      answer_text: answerText,
    }),
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

  return (await res.json()) as AnswerResponse
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
