/**
 * App — wires the interview together. The ComplaintBar morphs hero → docked; once
 * started, the page is a three-zone differential workspace (single column, stacked):
 *
 *   1. ComplaintBar (hero ↔ docked) — also hosts the page-wide "Re-score" control
 *   2. DifferentialGrid — orientation: current scores + red flags, visible immediately
 *   3. HistoryCard — orientation: history status (collapsed-by-default pinned entry point)
 *   4. SuggestionPool — action: what to ask next ("Expand full card" jumps to arm/history)
 *   5. OpenArmsLane — up to 3 full arm cards the clinician is actively working
 *   6. AnsweredLog — the chronological record (evolved Trace Viewer)
 *
 * Orientation surfaces (2–3) sit ABOVE the action surface (4): the clinician sees the
 * current differential + history status before being prompted to act.
 *
 * Drafts are a SINGLE shared store in useInterview (keyed by question_id); every card
 * reads/writes it, and the global "Re-score" control submits all pending drafts at once.
 * All data comes from the two SSE streams (triage + answer) via useInterview — no mocks.
 */

import { useRef, useState } from "react"

import { AnsweredLog } from "@/components/AnsweredLog"
import { ComplaintBar } from "@/components/ComplaintBar"
import { DifferentialGrid } from "@/components/DifferentialGrid"
import { HistoryCard } from "@/components/HistoryCard"
import { OpenArmsLane } from "@/components/OpenArmsLane"
import { SuggestionPool } from "@/components/SuggestionPool"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CUSTOM_ARM_ID,
  GLOBAL_RESCORE_ID,
  HISTORY_CARD_ID,
  SUGGESTION_CARD_ID,
  useInterview,
} from "@/hooks/useInterview"

/** Grid placeholder shown after submit but before the `triage` event lands — sized to the
 *  closed-grid tiles so there's no shape jump when real arms arrive. */
function GridSkeleton() {
  return (
    <div
      className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4"
      aria-label="Scoring diagnostic arms"
    >
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="flex flex-col items-center gap-2 rounded-xl border border-border bg-card px-3 py-4"
        >
          <Skeleton className="size-13 rounded-full" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-2 w-12" />
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const iv = useInterview()
  const [barHeight, setBarHeight] = useState(0)
  // Pulse target for the lane: bumping `signal` for an arm makes its lane card scroll
  // into view + flash. Used when "Expand full card" targets an arm (so an already-open
  // arm doesn't feel like a silent no-op, and a newly-opened one scrolls into view).
  const [pulse, setPulse] = useState<{ name: string | null; signal: number }>({
    name: null,
    signal: 0,
  })
  const historyRef = useRef<HTMLDivElement>(null)
  // General History's expand state lives HERE (not inside HistoryCard) so a history-
  // targeted suggestion's "Expand full card" can open it directly — scrolling to a still-
  // collapsed tile would be a silent no-op, the same failure the lane pulse already fixes.
  const [historyExpanded, setHistoryExpanded] = useState(false)

  const busy =
    iv.status.kind === "scoring" ||
    iv.status.kind === "generating" ||
    iv.status.kind === "rescoring"
  const generating = iv.status.kind === "generating"

  // Names of clinician-added arms, so the suggestion pool can mark a source-arm tag as
  // "added by you" (the grid tile / lane card read arm.source directly).
  const clinicianArmNames = new Set(
    iv.arms.filter((a) => a.source === "clinician").map((a) => a.name),
  )

  // From a suggestion's "Expand full card": open the arm (no-op if already open) and
  // pulse it. Grid-tile taps go straight to iv.openArm (no pulse) — the arm was closed,
  // so its new lane card is its own feedback.
  function openArmFromSuggestion(armName: string) {
    iv.openArm(armName)
    setPulse((p) => ({ name: armName, signal: p.signal + 1 }))
  }

  // General History isn't lane-eligible, so "expand" for a history suggestion means open
  // its (collapsed-by-default) card AND scroll it into view. Expand first, then scroll on
  // the next frame so the now-expanded card is what gets centred.
  function openHistory() {
    setHistoryExpanded(true)
    requestAnimationFrame(() =>
      historyRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <ComplaintBar
        docked={iv.started}
        busy={busy}
        status={iv.status}
        onStart={iv.start}
        onHeightChange={setBarHeight}
        pendingDraftCount={iv.pendingDraftCount}
        rescoreSubmitting={iv.submittingArm === GLOBAL_RESCORE_ID}
        onRescoreAll={iv.submitAllDrafts}
      />

      <main
        className="mx-auto max-w-5xl space-y-6 px-4 pb-24 transition-[padding] duration-500 ease-out"
        style={{ paddingTop: iv.started ? barHeight + 24 : 0 }}
      >
        {iv.started && (
          <>
            {/* 1. Orientation — the differential (current scores + red flags), shown
                immediately so the clinician is oriented before being prompted to act. */}
            {iv.arms.length === 0 ? (
              <GridSkeleton />
            ) : (
              <DifferentialGrid
                arms={iv.arms}
                openArms={iv.openArms}
                recentTransitions={iv.recentTransitions}
                rescoringArmNames={iv.rescoringArmNames}
                suggestions={iv.suggestions}
                leaderName={iv.leaderName}
                onOpen={iv.openArm}
                onAddCustomArms={iv.addCustomArms}
                adding={iv.submittingArm === CUSTOM_ARM_ID}
                busy={busy}
              />
            )}

            {/* 2. Orientation — General History status (collapsed-by-default pinned entry
                point). Wrapped so openHistory can scroll to it. */}
            {iv.historyChecklist && (
              <div ref={historyRef}>
                <HistoryCard
                  checklist={iv.historyChecklist}
                  answeredHistory={iv.answeredHistory}
                  submitting={iv.submittingArm === HISTORY_CARD_ID}
                  busy={busy}
                  onAnswerBatch={iv.answerBatch}
                  expanded={historyExpanded}
                  onExpandedChange={setHistoryExpanded}
                  drafts={iv.drafts}
                  onDraftChange={iv.setDraft}
                  onClearDrafts={iv.clearDrafts}
                  pendingDraftCount={iv.pendingDraftCount}
                />
              </div>
            )}

            {/* 3. Action — the ranked "what to ask next" surface. */}
            <SuggestionPool
              suggestions={iv.suggestions}
              busy={busy}
              submitting={iv.submittingArm === SUGGESTION_CARD_ID}
              onAnswerBatch={iv.answerBatch}
              onOpenArm={openArmFromSuggestion}
              onOpenHistory={openHistory}
              drafts={iv.drafts}
              onDraftChange={iv.setDraft}
              onClearDrafts={iv.clearDrafts}
              pendingDraftCount={iv.pendingDraftCount}
              clinicianArmNames={clinicianArmNames}
            />

            {/* 4. Open Cards Lane — the arms being actively worked (renders nothing when
                empty). */}
            <OpenArmsLane
              openArms={iv.openArms}
              arms={iv.arms}
              leaderName={iv.leaderName}
              recentTransitions={iv.recentTransitions}
              rescoringArmNames={iv.rescoringArmNames}
              generating={generating}
              expandingArms={iv.expandingArms}
              submittingArm={iv.submittingArm}
              busy={busy}
              onAnswerBatch={iv.answerBatch}
              onClose={iv.closeArm}
              drafts={iv.drafts}
              onDraftChange={iv.setDraft}
              onClearDrafts={iv.clearDrafts}
              pendingDraftCount={iv.pendingDraftCount}
              pulse={pulse}
            />

            {/* 5. Answered log (full width, the evolved Trace Viewer). */}
            <AnsweredLog entries={iv.answeredLog} />
          </>
        )}
      </main>
    </div>
  )
}
