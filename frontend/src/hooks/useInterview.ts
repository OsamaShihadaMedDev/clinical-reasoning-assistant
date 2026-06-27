/**
 * useInterview — the single orchestration hook for one interview session.
 *
 * It owns everything the UI derives from the backend: the streamed TriageOutput, the
 * general-history checklist, the staged SSE status, the suggestion pool, the answered
 * log, and the transient per-arm score-transition map. Components stay presentational;
 * this is where the agent loop's client-side state lives.
 *
 * Two streams feed it, both SSE but different transports:
 *  - `openTriageStream` (GET EventSource) — initial interview: history -> arms ->
 *    arm questions -> suggestions -> done.
 *  - `streamAnswers` (POST fetch+ReadableStream) — each card submit: rescoring ->
 *    rescored -> ranking_suggestions -> done. The staged events drive `status`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { expandArm as expandArmRequest, openTriageStream, streamAnswers } from "@/api/client"
import type {
  DiagnosticArm,
  HistoryChecklist,
  ScoreTransition,
  SuggestionBatch,
  TriageOutput,
} from "@/types"

/** Card identity used for the suggestion pool / General History card in `submittingArm`
 *  (arm cards use their arm name). Sentinels that can't collide with a real arm name. */
export const HISTORY_CARD_ID = "__history__"
export const SUGGESTION_CARD_ID = "__suggestions__"

/** Streaming status surfaced near the docked bar (drives StreamingStatus). The
 *  `rescoring` kind now carries the SSE stage so the UI can show distinct sub-labels
 *  ("Re-scoring arms…" -> "Updating differential…" -> "Ranking next questions…"). */
export type StreamStatus =
  | { kind: "idle" }
  | { kind: "scoring" }
  | { kind: "generating"; total: number; filled: number; current: string | null }
  | { kind: "ready" }
  | { kind: "rescoring"; stage: "rescoring" | "rescored" | "ranking_suggestions" }
  | { kind: "error"; detail: string }

/** One answered question in the chronological log. Built PER answered question (a batch
 *  of 3 makes 3 entries). The backend's ScoreTransition.trigger_answer is the whole
 *  batch joined, so it can't attribute a specific move to a specific answer — we
 *  therefore duplicate the batch's full `transitions` onto each entry of that batch
 *  rather than invent a per-answer attribution the backend doesn't have. */
export interface AnsweredLogEntry {
  id: number
  questionText: string
  answerText: string
  isHistoryQuestion: boolean
  transitions: ScoreTransition[]
  timestamp: number
}

/**
 * Decide the current leader given the previous one.
 * - The leader is the arm with the highest relevance_score.
 * - A tie is NOT a leadership change: if the previous leader still shares the top
 *   score, it stays leader.
 * - Leadership only moves when some arm is STRICTLY above the previous leader.
 */
function computeLeader(
  arms: DiagnosticArm[],
  prevLeader: string | null,
): string | null {
  if (arms.length === 0) return null
  const max = Math.max(...arms.map((a) => a.relevance_score))
  if (
    prevLeader &&
    arms.some((a) => a.name === prevLeader && a.relevance_score === max)
  ) {
    return prevLeader
  }
  return arms.find((a) => a.relevance_score === max)!.name
}

export function useInterview() {
  const [started, setStarted] = useState(false)
  const [triage, setTriage] = useState<TriageOutput | null>(null)
  // General-history checklist (arrives on the SSE `history` event) and the locally-
  // tracked answers to it (the answer stream returns only arms+transitions+suggestions,
  // not history state, so we mark history answers client-side).
  const [historyChecklist, setHistoryChecklist] =
    useState<HistoryChecklist | null>(null)
  const [answeredHistory, setAnsweredHistory] = useState<Record<string, string>>({})
  // The ranked "what to ask next" pool (SSE `suggestions` event at start; refreshed on
  // every answer stream's `done`).
  const [suggestions, setSuggestions] = useState<SuggestionBatch | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [status, setStatus] = useState<StreamStatus>({ kind: "idle" })
  // Which arm's full question detail is expanded (tap a differential-strip card). A
  // single selection replaces the old multi-open accordion set, since the strip is now
  // the primary view and only one arm's full questions show at a time.
  const [selectedArm, setSelectedArm] = useState<string | null>(null)
  const [leaderName, setLeaderName] = useState<string | null>(null)
  const [answeredLog, setAnsweredLog] = useState<AnsweredLogEntry[]>([])
  const [recentTransitions, setRecentTransitions] = useState<
    Record<string, ScoreTransition>
  >({})
  // Which card currently has a batch submit in flight (an arm name, HISTORY_CARD_ID, or
  // SUGGESTION_CARD_ID) — drives that card's submit-button loading state.
  const [submittingArm, setSubmittingArm] = useState<string | null>(null)
  // Arm names whose questions are being lazily generated on demand (top-N fan-out
  // skipped them; the user just expanded one). Drives a per-arm loading skeleton.
  const [expandingArms, setExpandingArms] = useState<Set<string>>(new Set())

  const cleanupRef = useRef<(() => void) | null>(null)
  const prevLeaderRef = useRef<string | null>(null)
  const logIdRef = useRef(0)

  // Arms in priority order (highest score first).
  const arms = useMemo(() => {
    if (!triage) return [] as DiagnosticArm[]
    return [...triage.arms].sort((a, b) => b.relevance_score - a.relevance_score)
  }, [triage])

  // Track the leader (for the differential strip's "Leading" highlight). Data-driven
  // and tie-stable via computeLeader. It no longer auto-expands anything — the arm
  // detail is user-driven now (tap a strip card) — it only marks the top card.
  useEffect(() => {
    if (arms.length === 0) return
    const next = computeLeader(arms, prevLeaderRef.current)
    if (next === prevLeaderRef.current) return
    prevLeaderRef.current = next
    setLeaderName(next)
  }, [arms])

  const start = useCallback(
    (chiefComplaint: string, patientContext: string) => {
      // Abort any prior stream and reset all session-scoped state.
      cleanupRef.current?.()
      setStarted(true)
      setTriage(null)
      setHistoryChecklist(null)
      setAnsweredHistory({})
      setSuggestions(null)
      setSessionId(null)
      setSelectedArm(null)
      setLeaderName(null)
      setAnsweredLog([])
      setRecentTransitions({})
      prevLeaderRef.current = null
      setStatus({ kind: "scoring" })

      cleanupRef.current = openTriageStream(chiefComplaint, patientContext, {
        onHistory: (checklist) => setHistoryChecklist(checklist),
        onTriage: (t) => {
          setTriage(t)
          const total = t.arms.filter((a) => a.status === "active").length
          setStatus({ kind: "generating", total, filled: 0, current: null })
        },
        onArmQuestions: (name, questions) => {
          setTriage((cur) =>
            cur
              ? {
                  ...cur,
                  arms: cur.arms.map((a) =>
                    a.name === name ? { ...a, questions } : a,
                  ),
                }
              : cur,
          )
          setStatus((s) =>
            s.kind === "generating"
              ? { ...s, filled: s.filled + 1, current: name }
              : s,
          )
        },
        onSuggestions: (s) => setSuggestions(s),
        onDone: (sid) => {
          setSessionId(sid)
          setStatus({ kind: "ready" })
        },
        onError: (detail) => setStatus({ kind: "error", detail }),
      })
    },
    [],
  )

  // Submit a BATCH of answers from ONE card (arm / history / suggestion pool) and
  // re-score once, consuming the staged SSE stream. `cardId` drives the card-level
  // loading state. Returns whether it succeeded, so the card can clear its drafts.
  const answerBatch = useCallback(
    async (
      cardId: string,
      answers: { question_id: string; answer_text: string }[],
    ): Promise<boolean> => {
      if (!sessionId || answers.length === 0) return false

      // Resolve each answered question's text + type NOW (before the stream replaces
      // `triage`), so the answered-log entries read correctly. Suggestion-pool answers
      // reference arm/history questions by the same ids, so this resolves them too.
      const historyById = new Map(
        (historyChecklist?.questions ?? []).map((q) => [q.id, q]),
      )
      const armQuestionById = new Map(
        (triage?.arms ?? []).flatMap((arm) => arm.questions).map((q) => [q.id, q]),
      )
      const resolved = answers.map((a) => {
        const hq = historyById.get(a.question_id)
        if (hq) {
          return { ...a, questionText: hq.question_text, isHistory: true }
        }
        const aq = armQuestionById.get(a.question_id)
        return { ...a, questionText: aq?.text ?? a.question_id, isHistory: false }
      })

      setSubmittingArm(cardId)
      setStatus({ kind: "rescoring", stage: "rescoring" })

      let ok = false
      await streamAnswers(sessionId, answers, {
        onRescoring: () => setStatus({ kind: "rescoring", stage: "rescoring" }),
        onRescored: (transitions) => {
          setStatus({ kind: "rescoring", stage: "rescored" })
          // Update the differential strip's per-arm deltas as soon as scores move,
          // before suggestions finish ranking.
          const map: Record<string, ScoreTransition> = {}
          for (const t of transitions) map[t.arm_name] = t
          setRecentTransitions(map)
        },
        onRankingSuggestions: () =>
          setStatus({ kind: "rescoring", stage: "ranking_suggestions" }),
        onDone: (res) => {
          setTriage(res.triage)
          setSuggestions(res.suggestions)

          // Mark any general-history answers in this batch (detected by checklist
          // membership — no backend id-format knowledge here).
          const newlyAnswered: Record<string, string> = {}
          for (const r of resolved) {
            if (r.isHistory) newlyAnswered[r.question_id] = r.answer_text
          }
          if (Object.keys(newlyAnswered).length > 0) {
            setAnsweredHistory((prev) => ({ ...prev, ...newlyAnswered }))
          }

          // One log entry per answered question, newest-first (continuity with the old
          // TraceLogPanel ordering). The batch's full transitions are duplicated onto
          // each entry — see AnsweredLogEntry's note on why per-answer attribution
          // isn't available from the backend.
          const now = Date.now()
          const entries: AnsweredLogEntry[] = resolved.map((r) => {
            logIdRef.current += 1
            return {
              id: logIdRef.current,
              questionText: r.questionText,
              answerText: r.answer_text,
              isHistoryQuestion: r.isHistory,
              transitions: res.transitions,
              timestamp: now,
            }
          })
          // Prepend reversed so that within one batch the first-answered reads on top.
          setAnsweredLog((log) => [...entries.reverse(), ...log])

          setStatus({ kind: "ready" })
          ok = true
        },
        onError: (detail) => setStatus({ kind: "error", detail }),
      })

      setSubmittingArm(null)
      return ok
    },
    [sessionId, historyChecklist, triage],
  )

  // Lazily generate questions for ONE arm the top-N fan-out skipped, when the user
  // expands it. Mirrors the backend's idempotent /api/arm/expand; the guards just avoid
  // pointless requests (all are also enforced server-side).
  const expandArm = useCallback(
    async (armName: string) => {
      if (!sessionId) return
      if (status.kind !== "ready") return
      const arm = triage?.arms.find((a) => a.name === armName)
      if (!arm || arm.status !== "active") return
      if (arm.questions.length > 0) return
      if (expandingArms.has(armName)) return

      setExpandingArms((s) => new Set(s).add(armName))
      try {
        const res = await expandArmRequest(sessionId, armName)
        setTriage((cur) =>
          cur
            ? {
                ...cur,
                arms: cur.arms.map((a) =>
                  a.name === armName ? { ...a, questions: res.arm.questions } : a,
                ),
              }
            : cur,
        )
      } catch (e) {
        setStatus({ kind: "error", detail: (e as Error).message })
      } finally {
        setExpandingArms((s) => {
          const next = new Set(s)
          next.delete(armName)
          return next
        })
      }
    },
    [sessionId, status, triage, expandingArms],
  )

  // Toggle the expanded arm detail; lazily generate its questions if it has none.
  const selectArm = useCallback(
    (armName: string) => {
      setSelectedArm((cur) => (cur === armName ? null : armName))
      void expandArm(armName)
    },
    [expandArm],
  )

  // Close the stream if the component unmounts mid-flight.
  useEffect(() => () => cleanupRef.current?.(), [])

  return {
    started,
    triage,
    arms,
    historyChecklist,
    answeredHistory,
    suggestions,
    sessionId,
    status,
    selectedArm,
    selectArm,
    leaderName,
    answeredLog,
    recentTransitions,
    submittingArm,
    expandingArms,
    start,
    answerBatch,
    expandArm,
  }
}
