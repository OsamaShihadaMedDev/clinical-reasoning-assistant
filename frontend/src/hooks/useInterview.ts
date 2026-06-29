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

import {
  expandArm as expandArmRequest,
  openTriageStream,
  streamAnswers,
  streamCustomArms,
} from "@/api/client"
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
/** Card identity for the page-wide "Re-score" control that submits EVERY pending draft at
 *  once (drives its own `submittingArm` loading state, same as the two above). */
export const GLOBAL_RESCORE_ID = "__global__"
/** Card identity for the "Add a custom diagnosis" control (drives its own submit/loading
 *  state via `submittingArm`, like the sentinels above). */
export const CUSTOM_ARM_ID = "__custom_arm__"

/** Streaming status surfaced near the docked bar (drives StreamingStatus). The
 *  `rescoring` kind now carries the SSE stage so the UI can show distinct sub-labels
 *  ("Re-scoring arms…" -> "Updating differential…" -> "Ranking next questions…"). */
export type StreamStatus =
  | { kind: "idle" }
  | { kind: "scoring" }
  | { kind: "generating"; total: number; filled: number; current: string | null }
  | { kind: "ready" }
  | {
      kind: "rescoring"
      stage: "adding_arms" | "rescoring" | "rescored" | "ranking_suggestions"
    }
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

/** How many arm cards the clinician can work at once in the Open Cards Lane. This is a
 *  WORKFLOW cap (how many hypotheses a clinician holds in hand), not a screen-size
 *  accommodation, so it is the SAME on mobile and desktop — it does not vary by
 *  breakpoint. Opening past the cap evicts the oldest-opened arm (index 0). */
export const MAX_OPEN_ARMS = 3

/**
 * Pure reducer for the open-arms list (extracted so the eviction invariants are unit-
 * testable without React): append `armName` unless it is already open (no-op, preserving
 * order and avoiding a duplicate), capping at MAX_OPEN_ARMS by evicting the oldest entry
 * (index 0). The list is ordered oldest -> newest by when each arm was opened.
 */
export function addOpenArm(current: string[], armName: string): string[] {
  if (current.includes(armName)) return current
  const next = [...current, armName]
  return next.length > MAX_OPEN_ARMS ? next.slice(1) : next
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
  // The arms whose FULL question card is open in the Open Cards Lane, ordered oldest ->
  // newest by when each was opened (index 0 = oldest). Capped at MAX_OPEN_ARMS; opening a
  // (cap+1)-th arm evicts index 0. Replaces the old single `selectedArm` so the clinician
  // can work up to three hypotheses side by side.
  const [openArms, setOpenArms] = useState<string[]>([])
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
  // Arm names whose SCORE is currently being recalculated (the in-flight re-score
  // window), distinct from `recentTransitions` which is the ALREADY-COMPLETED deltas.
  // The backend re-scores all active arms together in one call (no partial-arm signal),
  // so this is "all active arms" for the rescoring/rescored/ranking stages; it drives a
  // localized gauge pulse on each affected card and is cleared on done/error.
  const [rescoringArmNames, setRescoringArmNames] = useState<Set<string>>(new Set())
  // ONE shared draft store, keyed by question_id (uniform across arm, suggestion-pool, and
  // history questions — all carry stable string ids). Lives here, not per component, for
  // two reasons: (1) the global "Re-score" control can gather pending drafts from EVERY
  // card at once; (2) the same question shown in two places (a suggestion mirrors an
  // arm/history question by id) shares one draft instead of two diverging copies — which
  // also structurally fixes the SuggestionPool overwrite bug (independent ids, no shared
  // scalar). Components are now presentational over this store.
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const setDraft = useCallback((questionId: string, text: string) => {
    setDrafts((cur) => ({ ...cur, [questionId]: text }))
  }, [])

  // Clears only the given ids — used by per-card submit (just that card's ids) and the
  // global submit (every id it just sent). Anything typed afterward (other ids) is left.
  const clearDrafts = useCallback((ids: string[]) => {
    setDrafts((cur) => {
      const next = { ...cur }
      for (const id of ids) delete next[id]
      return next
    })
  }, [])

  // Count of non-empty pending drafts across the WHOLE store — disables the global
  // re-score control at zero, shows its "N pending" count, and lets each card cheaply
  // derive "are there drafts OUTSIDE my own ids" (count > my own pending) for its nudge
  // text, without re-scanning the store per component.
  const pendingDraftCount = useMemo(
    () => Object.values(drafts).filter((t) => t.trim().length > 0).length,
    [drafts],
  )

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
      setOpenArms([])
      setLeaderName(null)
      setAnsweredLog([])
      setRecentTransitions({})
      setRescoringArmNames(new Set())
      setDrafts({})
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
      // Mark every active arm as in-flight for the gauge pulse (the backend re-scores
      // them all together). Cleared on the stream's done/error below.
      setRescoringArmNames(
        new Set(
          (triage?.arms ?? [])
            .filter((a) => a.status === "active")
            .map((a) => a.name),
        ),
      )

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

          setRescoringArmNames(new Set()) // new scores landed — stop the gauge pulse
          setStatus({ kind: "ready" })
          ok = true
        },
        onError: (detail) => {
          setRescoringArmNames(new Set()) // re-score failed — don't leave a stale pulse
          setStatus({ kind: "error", detail })
        },
      })

      setSubmittingArm(null)
      return ok
    },
    [sessionId, historyChecklist, triage],
  )

  // The global "Re-score" control: gather EVERY non-empty draft across all cards and
  // submit them as ONE combined batch. Reuses answerBatch — the exact same SSE-staged
  // re-score path as any per-card submit, just with a wider answers[] and a sentinel id.
  // Clears only the ids it actually sent on success (drafts typed afterward stay).
  const submitAllDrafts = useCallback(async (): Promise<boolean> => {
    const answers = Object.entries(drafts)
      .map(([question_id, value]) => ({ question_id, answer_text: value.trim() }))
      .filter((a) => a.answer_text.length > 0)
    if (answers.length === 0) return false
    const ok = await answerBatch(GLOBAL_RESCORE_ID, answers)
    if (ok) clearDrafts(answers.map((a) => a.question_id))
    return ok
  }, [drafts, answerBatch, clearDrafts])

  // Add one or more clinician-named diagnostic arms, scored TOGETHER server-side against
  // the case-so-far. Adding a diagnosis IS a re-score, so this drives the SAME staged
  // status as answerBatch (with a leading `adding_arms` stage) and the same gauge pulse —
  // it should feel like every other re-score, not a separate loading state. It does NOT
  // create an answered-log entry (no question was answered); the new arms appearing in the
  // differential + the gauge deltas are the visible feedback.
  const addCustomArms = useCallback(
    async (names: string[]): Promise<boolean> => {
      if (!sessionId || names.length === 0) return false

      setSubmittingArm(CUSTOM_ARM_ID)
      setStatus({ kind: "rescoring", stage: "adding_arms" })
      // Pulse the EXISTING active arms for the in-flight window (the new arms don't exist
      // client-side until `done`); cleared on done/error, exactly like answerBatch.
      setRescoringArmNames(
        new Set(
          (triage?.arms ?? [])
            .filter((a) => a.status === "active")
            .map((a) => a.name),
        ),
      )

      let ok = false
      await streamCustomArms(sessionId, names, {
        onAddingArms: () => setStatus({ kind: "rescoring", stage: "adding_arms" }),
        onRescoring: () => setStatus({ kind: "rescoring", stage: "rescoring" }),
        onRescored: (transitions) => {
          setStatus({ kind: "rescoring", stage: "rescored" })
          const map: Record<string, ScoreTransition> = {}
          for (const t of transitions) map[t.arm_name] = t
          setRecentTransitions(map)
        },
        onRankingSuggestions: () =>
          setStatus({ kind: "rescoring", stage: "ranking_suggestions" }),
        onDone: (res) => {
          setTriage(res.triage)
          setSuggestions(res.suggestions)
          setRescoringArmNames(new Set())
          setStatus({ kind: "ready" })
          ok = true
        },
        onError: (detail) => {
          setRescoringArmNames(new Set())
          setStatus({ kind: "error", detail })
        },
      })

      setSubmittingArm(null)
      return ok
    },
    [sessionId, triage],
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

  // Open an arm's full card in the lane: add it (capped, evicting the oldest) and lazily
  // generate its questions if the top-N fan-out skipped it. A no-op if already open — the
  // caller is responsible for scrolling/highlighting the existing lane card (App.tsx).
  const openArm = useCallback(
    (armName: string) => {
      setOpenArms((cur) => addOpenArm(cur, armName))
      void expandArm(armName) // unchanged lazy question generation; idempotent server-side
    },
    [expandArm],
  )

  // Close one arm's card, removing it from the lane (leaving the others as-is).
  const closeArm = useCallback((armName: string) => {
    setOpenArms((cur) => cur.filter((n) => n !== armName))
  }, [])

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
    openArms,
    openArm,
    closeArm,
    leaderName,
    answeredLog,
    recentTransitions,
    submittingArm,
    expandingArms,
    rescoringArmNames,
    drafts,
    setDraft,
    clearDrafts,
    pendingDraftCount,
    start,
    answerBatch,
    submitAllDrafts,
    addCustomArms,
    expandArm,
  }
}
