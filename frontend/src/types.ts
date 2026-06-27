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

/** Patient population category. Mirrors the backend `PatientCategory` enum's
 *  string values (history.py). */
export type PatientCategory =
  | "pediatric"
  | "ob_gyn"
  | "surgical"
  | "geriatric"
  | "adult_general"

/** One general-history question in a population checklist. Mirrors `HistoryQuestion`.
 *  Note the fields differ from ClinicalQuestion: `question_text`/`rationale`, and no
 *  score/intent — these aren't weighed against each other like diagnostic arms. */
export interface HistoryQuestion {
  id: string
  question_text: string
  rationale: string
}

/** The general-history checklist for a patient's population. Mirrors `HistoryChecklist`
 *  and is the payload of the SSE `history` event (and the `history` field on the
 *  POST /api/triage response). Rendered as its own card above the diagnostic arms. */
export interface HistoryChecklist {
  category: PatientCategory
  questions: HistoryQuestion[]
  /** True only when classification fell back to adult_general for lack of context —
   *  drives whether the assumption note shows (CLAUDE.md-style "did we have to guess"). */
  assumed_default: boolean
  /** Always populated; the literal text shown in the assumption note when
   *  `assumed_default` is true. */
  category_reasoning: string
}

/** Response body of `POST /api/arm/expand` (see `ArmExpandResponse` in main.py):
 *  the single arm with its questions filled in. Backend top-N auto-generate means
 *  arms outside the top 3 arrive with an empty `questions` list; expanding one in
 *  the UI lazily generates them on demand. The call is idempotent server-side, so
 *  an already-populated arm comes back unchanged. */
export interface ArmExpandResponse {
  arm: DiagnosticArm
}
