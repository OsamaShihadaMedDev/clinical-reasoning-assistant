/**
 * TypeScript mirrors of the backend Pydantic contracts. These are field-for-field
 * copies of `backend/app/models/clinical.py`, `triage.py`, and `trace.py` — the same
 * typed handoff contracts the agents use, just on the client side. Do NOT add fields
 * the backend doesn't send; if a shape here drifts from the Pydantic model, the
 * Pydantic model is the source of truth.
 */

/** One targeted history-taking question belonging to a diagnostic arm.
 *  Mirrors `ClinicalQuestion`. */
export interface ClinicalQuestion {
  id: string
  text: string
  diagnostic_intent: string
  answered: boolean
  /** Populated only once `answered` is true (backend invariant). */
  answer_text: string | null
}

/** One diagnostic arm and its questions. Mirrors `DiagnosticArm`.
 *  `relevance_score` is bounded [0, 1] by the backend contract. */
export interface DiagnosticArm {
  name: string
  relevance_score: number
  reasoning: string
  status: "active" | "deprioritized"
  questions: ClinicalQuestion[]
}

/** The Triage Agent's output: the complaint plus its scored arms.
 *  Mirrors `TriageOutput`. This is the payload of the SSE `triage` event. */
export interface TriageOutput {
  chief_complaint: string
  arms: DiagnosticArm[]
}

/** One arm's score moving old -> new, with the answer that caused it.
 *  Mirrors `ScoreTransition`. The Trace Viewer (CLAUDE.md 6b) renders these. */
export interface ScoreTransition {
  arm_name: string
  old_score: number
  new_score: number
  trigger_answer: string
}

/** Response body of `POST /api/answer` (see `AnswerResponse` in main.py): the
 *  updated triage plus only the arms whose score changed for this answer. */
export interface AnswerResponse {
  triage: TriageOutput
  transitions: ScoreTransition[]
}

/** Payload of the SSE `arm_questions` event: a single arm's just-generated
 *  questions, identified by name (see `_triage_event_stream` in main.py). */
export interface ArmQuestionsEvent {
  name: string
  questions: ClinicalQuestion[]
}

/** Response body of `POST /api/arm/expand` (see `ArmExpandResponse` in main.py):
 *  the single arm with its questions filled in. Backend top-N auto-generate means
 *  arms outside the top 3 arrive with an empty `questions` list; expanding one in
 *  the UI lazily generates them on demand. The call is idempotent server-side, so
 *  an already-populated arm comes back unchanged. */
export interface ArmExpandResponse {
  arm: DiagnosticArm
}
