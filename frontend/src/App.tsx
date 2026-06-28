/**
 * App — wires the interview together. The ComplaintBar morphs hero → docked; once
 * started, the page is a three-zone differential workspace (single column, stacked):
 *
 *   1. ComplaintBar (hero ↔ docked)
 *   2. SuggestionPool — the ranked "what to ask next" surface (inline answer + a new
 *      "Expand full card" jump to the relevant arm/General History)
 *   3. OpenArmsLane — up to 3 full arm cards the clinician is actively working
 *   4. DifferentialGrid — the remaining arms as compact closed tiles; the full General
 *      History card is pinned FIRST in this same area (option b: rendered here by App,
 *      not threaded through the grid, to avoid prop-drilling its 5 props)
 *   5. AnsweredLog — the chronological record (evolved Trace Viewer)
 *
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

  const busy =
    iv.status.kind === "scoring" ||
    iv.status.kind === "generating" ||
    iv.status.kind === "rescoring"
  const generating = iv.status.kind === "generating"

  // From a suggestion's "Expand full card": open the arm (no-op if already open) and
  // pulse it. Grid-tile taps go straight to iv.openArm (no pulse) — the arm was closed,
  // so its new lane card is its own feedback.
  function openArmFromSuggestion(armName: string) {
    iv.openArm(armName)
    setPulse((p) => ({ name: armName, signal: p.signal + 1 }))
  }

  // General History isn't lane-eligible (pinned in the differential area), so "expand"
  // for a history suggestion means scroll it into view. It's never mobile-collapsed
  // (HistoryCard has no collapse state), so scrolling is the whole action.
  function openHistory() {
    historyRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
  }

  return (
    <div className="min-h-screen bg-background">
      <ComplaintBar
        docked={iv.started}
        busy={busy}
        status={iv.status}
        onStart={iv.start}
        onHeightChange={setBarHeight}
      />

      <main
        className="mx-auto max-w-5xl space-y-6 px-4 pb-24 transition-[padding] duration-500 ease-out"
        style={{ paddingTop: iv.started ? barHeight + 24 : 0 }}
      >
        {iv.started && (
          <>
            {/* 1. Ranked suggestion pool — the primary "what to ask next" surface. */}
            <SuggestionPool
              suggestions={iv.suggestions}
              busy={busy}
              submitting={iv.submittingArm === SUGGESTION_CARD_ID}
              onAnswerBatch={iv.answerBatch}
              onOpenArm={openArmFromSuggestion}
              onOpenHistory={openHistory}
            />

            {/* 2. Open Cards Lane — the arms being actively worked (renders nothing when
                empty). */}
            <OpenArmsLane
              openArms={iv.openArms}
              arms={iv.arms}
              leaderName={iv.leaderName}
              recentTransitions={iv.recentTransitions}
              generating={generating}
              expandingArms={iv.expandingArms}
              submittingArm={iv.submittingArm}
              busy={busy}
              onAnswerBatch={iv.answerBatch}
              onClose={iv.closeArm}
              pulse={pulse}
            />

            {/* 3. General History — pinned first in the differential area (see header
                comment / option b). Wrapped so the suggestion "expand" can scroll to it. */}
            {iv.historyChecklist && (
              <div ref={historyRef}>
                <HistoryCard
                  checklist={iv.historyChecklist}
                  answeredHistory={iv.answeredHistory}
                  submitting={iv.submittingArm === HISTORY_CARD_ID}
                  busy={busy}
                  onAnswerBatch={iv.answerBatch}
                />
              </div>
            )}

            {/* 4. Closed Grid — the remaining (not-open) arms as compact tiles. */}
            {iv.arms.length === 0 ? (
              <GridSkeleton />
            ) : (
              <DifferentialGrid
                arms={iv.arms}
                openArms={iv.openArms}
                recentTransitions={iv.recentTransitions}
                suggestions={iv.suggestions}
                leaderName={iv.leaderName}
                onOpen={iv.openArm}
              />
            )}

            {/* 5. Answered log (full width, the evolved Trace Viewer). */}
            <AnsweredLog entries={iv.answeredLog} />
          </>
        )}
      </main>
    </div>
  )
}
