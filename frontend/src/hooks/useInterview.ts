/**
 * useInterview — the single orchestration hook for one interview session.
 *
 * It owns everything the UI derives from the backend: the streamed TriageOutput,
 * the SSE progress status, the controlled accordion open-set, the accumulating
 * trace log, and the transient per-arm score-transition map. Components stay
 * presentational; this is where the agent loop's client-side state lives.
 *
 * The one piece of genuinely tricky behaviour here is the LEADER auto-expand
 * (CLAUDE.md 6b demo behaviour): see the leadership effect and computeLeader.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { expandArm as expandArmRequest, openTriageStream, submitAnswers } from "@/api/client"
import type {
  DiagnosticArm,
  HistoryChecklist,
  ScoreTransition,
  TriageOutput,
} from "@/types"

/** Card identity used for the General History card in `submittingArm` (arm cards use
 *  their arm name). A sentinel that can't collide with a real arm name. */
export const HISTORY_CARD_ID = "__history__"

/** Streaming status surfaced near the docked bar (drives StreamingStatus). */
export type StreamStatus =
  | { kind: "idle" }
  | { kind: "scoring" }
  | { kind: "generating"; total: number; filled: number; current: string | null }
  | { kind: "ready" }
  | { kind: "rescoring" }
  | { kind: "error"; detail: string }

/** One answer's worth of trace, grouped like demo.html: the triggering answer
 *  plus the arms that moved because of it. Newest entries are prepended. */
export interface TraceEntry {
  id: number
  answer: string
  transitions: ScoreTransition[]
}

/**
 * Decide the current leader given the previous one.
 * - The leader is the arm with the highest relevance_score.
 * - A tie is NOT a leadership change: if the previous leader still shares the top
 *   score, it stays leader (so a score *decrease* that doesn't change who's on top,
 *   or another arm merely *tying* the top, does not fire the auto-expand).
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
  // General-history checklist (arrives on the SSE `history` event, before triage) and
  // the locally-tracked answers to it. We track answeredHistory client-side because
  // /api/answer returns only the re-scored arms+transitions, not the history state.
  const [historyChecklist, setHistoryChecklist] =
    useState<HistoryChecklist | null>(null)
  const [answeredHistory, setAnsweredHistory] = useState<Record<string, string>>({})
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [status, setStatus] = useState<StreamStatus>({ kind: "idle" })
  const [openArms, setOpenArms] = useState<string[]>([])
  const [leaderName, setLeaderName] = useState<string | null>(null)
  const [traceLog, setTraceLog] = useState<TraceEntry[]>([])
  const [recentTransitions, setRecentTransitions] = useState<
    Record<string, ScoreTransition>
  >({})
  // Which card currently has a batch submit in flight (an arm name, or HISTORY_CARD_ID
  // for the General History card). Replaces the old per-question answeringId — a
  // card-level submit no longer maps to a single question id.
  const [submittingArm, setSubmittingArm] = useState<string | null>(null)
  // Arm names whose questions are being lazily generated on demand (top-N fan-out
  // skipped them; the user just expanded one). Drives a per-arm loading skeleton.
  const [expandingArms, setExpandingArms] = useState<Set<string>>(new Set())

  const cleanupRef = useRef<(() => void) | null>(null)
  const prevLeaderRef = useRef<string | null>(null)
  const traceIdRef = useRef(0)

  // Arms in priority order (highest score first). Memoised on `triage` so the
  // leadership effect below only re-runs when the triage object actually changes,
  // not on every render.
  const arms = useMemo(() => {
    if (!triage) return [] as DiagnosticArm[]
    return [...triage.arms].sort((a, b) => b.relevance_score - a.relevance_score)
  }, [triage])

  // Leader auto-expand/collapse. This is data-driven, not click-driven, so it lives
  // here (diffing previous vs current leader) rather than inside the Accordion's own
  // open/close handler. On an actual leadership change it touches ONLY two arms —
  // collapse the old leader, expand the new one — and never re-asserts itself
  // between changes, so the user's manual toggles on every other arm are preserved.
  useEffect(() => {
    if (arms.length === 0) return
    const prev = prevLeaderRef.current
    const next = computeLeader(arms, prev)
    if (next === prev) return

    setOpenArms((open) => {
      const updated = prev ? open.filter((n) => n !== prev) : [...open]
      if (next && !updated.includes(next)) updated.push(next)
      return updated
    })
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
      setSessionId(null)
      setOpenArms([])
      setLeaderName(null)
      setTraceLog([])
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
        onDone: (sid) => {
          setSessionId(sid)
          setStatus({ kind: "ready" })
        },
        onError: (detail) => setStatus({ kind: "error", detail }),
      })
    },
    [],
  )

  // Submit a BATCH of answers from ONE card (arm card or General History card) and
  // re-score once. `cardId` is the submitting card's identity (arm name, or
  // HISTORY_CARD_ID) — only used to drive the card-level loading state. Returns whether
  // the submit succeeded, so the card can clear exactly the drafts it submitted.
  const answerBatch = useCallback(
    async (
      cardId: string,
      answers: { question_id: string; answer_text: string }[],
    ): Promise<boolean> => {
      if (!sessionId || answers.length === 0) return false
      setSubmittingArm(cardId)
      setStatus({ kind: "rescoring" })
      try {
        const res = await submitAnswers(sessionId, answers)
        setTriage(res.triage)

        // Record any general-history answers in this batch locally (the response
        // carries only arms+transitions, not history state). Detected by membership in
        // the checklist rather than an id prefix, so the frontend keeps no knowledge of
        // the backend id format.
        const historyIds = new Set(
          historyChecklist?.questions.map((q) => q.id) ?? [],
        )
        const newlyAnswered: Record<string, string> = {}
        for (const a of answers) {
          if (historyIds.has(a.question_id)) newlyAnswered[a.question_id] = a.answer_text
        }
        if (Object.keys(newlyAnswered).length > 0) {
          setAnsweredHistory((prev) => ({ ...prev, ...newlyAnswered }))
        }

        // Transient per-arm old->new indicator. Replacing the whole map (rather than
        // merging) means only arms that moved on THIS submit carry a fresh object,
        // so each ScoreTransitionIndicator self-fades exactly once per change.
        const map: Record<string, ScoreTransition> = {}
        for (const t of res.transitions) map[t.arm_name] = t
        setRecentTransitions(map)

        // Trace log entry, newest first. The answer is the batch joined into one
        // string, matching the backend's joined ScoreTransition.trigger_answer.
        const joined = answers.map((a) => a.answer_text).join("; ")
        traceIdRef.current += 1
        setTraceLog((log) => [
          { id: traceIdRef.current, answer: joined, transitions: res.transitions },
          ...log,
        ])
        setStatus({ kind: "ready" })
        return true
      } catch (e) {
        setStatus({ kind: "error", detail: (e as Error).message })
        return false
      } finally {
        setSubmittingArm(null)
      }
    },
    [sessionId, historyChecklist],
  )

  // Lazily generate questions for ONE arm the top-N fan-out skipped, the moment the
  // user expands it. Mirrors the backend's idempotent /api/arm/expand: every guard
  // here is also enforced server-side, so this is purely to avoid pointless requests:
  //  - need a live session id (only set after the stream's `done` event);
  //  - only when settled (`ready`) — during `generating` the SSE stream is already
  //    filling the top-3, and during `rescoring` a promotion is auto-generated inside
  //    the /api/answer call, so a manual expand then would race/duplicate;
  //  - skip arms that already have questions (idempotent no-op anyway) or aren't
  //    active, and don't fire twice for an arm already in flight.
  // setExpandingArms runs synchronously in the same event as setOpenArms (App calls
  // this right after it), so React batches them and the skeleton shows on the very
  // next render — no "No questions" flash before the fetch starts.
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

  // Close the stream if the component unmounts mid-flight.
  useEffect(() => () => cleanupRef.current?.(), [])

  return {
    started,
    triage,
    arms,
    historyChecklist,
    answeredHistory,
    sessionId,
    status,
    openArms,
    setOpenArms,
    leaderName,
    traceLog,
    recentTransitions,
    submittingArm,
    expandingArms,
    start,
    answerBatch,
    expandArm,
  }
}
