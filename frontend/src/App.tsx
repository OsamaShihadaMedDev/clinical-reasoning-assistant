/**
 * App — wires the interview together. The ComplaintBar morphs hero → docked; once
 * started, the page is a differential workspace. The numbered zones below stack in a
 * single LEFT column; a right-side InvestigationPane (zone 7) appears beside them only
 * after the first "Suggest workup" click, turning the layout two-column at lg+.
 *
 *   1. ComplaintBar (hero ↔ docked) — also hosts the page-wide "Re-score" AND the
 *      on-demand "Suggest workup" control
 *   2. DifferentialGrid — orientation: current scores + red flags, visible immediately
 *   3. RescoreSummary — orientation: what just changed and why, after the latest
 *      re-score only (renders nothing until the first re-score has happened)
 *   4. HistoryCard — orientation: history status (collapsed-by-default pinned entry point)
 *   5. SuggestionPool — action: what to ask next ("Expand full card" jumps to arm/history)
 *   6. OpenArmsLane — up to 3 full arm cards the clinician is actively working
 *   7. AnsweredLog — the chronological record, now pure Q&A (scores moved to
 *      RescoreSummary above, kept out of the per-question transcript)
 *   8. InvestigationPane (right column, on-demand) — tests/imaging to consider, a
 *      read-only snapshot the clinician explicitly requests; not in the re-score loop.
 *
 * Orientation surfaces (2–3) sit ABOVE the action surface (4): the clinician sees the
 * current differential + history status before being prompted to act.
 *
 * Drafts are a SINGLE shared store in useInterview (keyed by question_id); every card
 * reads/writes it, and the global "Re-score" control submits all pending drafts at once.
 * All data comes from the two SSE streams (triage + answer) via useInterview — no mocks.
 */

import { useEffect, useRef, useState } from "react"

import { AnsweredLog } from "@/components/AnsweredLog"
import { ComplaintBar } from "@/components/ComplaintBar"
import { DifferentialGrid } from "@/components/DifferentialGrid"
import { HistoryCard } from "@/components/HistoryCard"
import { InvestigationPane } from "@/components/InvestigationPane"
import { OpenArmsLane } from "@/components/OpenArmsLane"
import { RescoreSummary } from "@/components/RescoreSummary"
import { SuggestionPool } from "@/components/SuggestionPool"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CUSTOM_ARM_ID,
  GLOBAL_RESCORE_ID,
  HISTORY_CARD_ID,
  INVESTIGATION_ID,
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
  // Measured height of the fixed disclaimer banner, so the docked ComplaintBar (via its
  // topOffset prop) and the main content below both clear it. Measured rather than a fixed
  // constant because the disclaimer text wraps to 2+ lines on narrow screens — a constant
  // would under-reserve on mobile and let the banner overlap the docked bar.
  const [bannerHeight, setBannerHeight] = useState(0)
  const bannerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = bannerRef.current
    if (!node) return
    const report = () => setBannerHeight(node.getBoundingClientRect().height)
    report()
    const observer = new ResizeObserver(report)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
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
      {/* Standing, non-dismissible disclaimer — visible in BOTH hero and docked states for
          the whole session. z-40 keeps it above ComplaintBar (z-30); everything below is
          offset by its measured height so nothing hides behind it. */}
      <div
        ref={bannerRef}
        className="fixed inset-x-0 top-0 z-40 border-b border-border bg-muted/80 px-4 py-1.5 text-center text-xs text-muted-foreground backdrop-blur-sm"
      >
        Demonstration tool using simulated patient cases — not for real patient care or
        clinical decision-making.
      </div>
      <ComplaintBar
        docked={iv.started}
        busy={busy}
        status={iv.status}
        onStart={iv.start}
        onHeightChange={setBarHeight}
        topOffset={bannerHeight}
        pendingDraftCount={iv.pendingDraftCount}
        rescoreSubmitting={iv.submittingArm === GLOBAL_RESCORE_ID}
        onRescoreAll={iv.submitAllDrafts}
        investigationsLoading={iv.submittingArm === INVESTIGATION_ID}
        onSuggestInvestigations={iv.requestInvestigations}
      />

      <main
        className="mx-auto max-w-5xl px-4 pb-24 transition-[padding] duration-500 ease-out"
        style={{ paddingTop: iv.started ? bannerHeight + barHeight + 24 : 0 }}
      >
        {iv.started && (
          // Two-column at lg+ ONLY once the workup pane exists; before that, the lone
          // flex-1 left column behaves exactly like the previous single column (no empty
          // space reserved for the pane). items-start lets the pane stick independently.
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
            <div className="min-w-0 flex-1 space-y-6">
            {/* 2. Orientation — the differential (current scores + red flags), shown
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

            {/* 3. Orientation — what the latest re-score moved and why. Renders nothing
                until the first re-score has happened. */}
            <RescoreSummary
              recentTransitions={iv.recentTransitions}
              arms={iv.arms}
            />

            {/* 4. Orientation — General History status (collapsed-by-default pinned entry
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

            {/* 5. Action — the ranked "what to ask next" surface. */}
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

            {/* 6. Open Cards Lane — the arms being actively worked (renders nothing when
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

            {/* 7. Answered log — pure Q&A transcript (scores moved to RescoreSummary). */}
            <AnsweredLog entries={iv.answeredLog} />
            </div>

            {/* 8. On-demand workup pane (right column). Rendered only after the first
                "Suggest workup" request, so no empty column is reserved beforehand. */}
            {iv.investigations !== null && (
              <aside className="w-full lg:w-80 lg:shrink-0">
                <InvestigationPane
                  batch={iv.investigations}
                  answeredCount={iv.investigationsAnsweredCount}
                  currentAnsweredCount={iv.totalAnsweredCount}
                  loading={iv.submittingArm === INVESTIGATION_ID}
                  onRefresh={iv.requestInvestigations}
                  stickyTop={bannerHeight + barHeight + 24}
                />
              </aside>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
