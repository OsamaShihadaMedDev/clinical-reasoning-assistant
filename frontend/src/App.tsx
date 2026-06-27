/**
 * App — wires the interview together. The ComplaintBar morphs hero → docked; once
 * started, the page stacks (single column): the DifferentialStrip (compact, all arms),
 * an inline full-question detail for whichever arm is tapped, the General History card,
 * the ranked SuggestionPool ("what to ask next"), and the AnsweredLog. All data comes
 * from the two SSE streams (triage + answer) — no mocks.
 */

import { useState } from "react"

import { AnsweredLog } from "@/components/AnsweredLog"
import { ComplaintBar } from "@/components/ComplaintBar"
import { DiagnosticArmCard } from "@/components/DiagnosticArmCard"
import { DifferentialStrip } from "@/components/DifferentialStrip"
import { HistoryCard } from "@/components/HistoryCard"
import { SuggestionPool } from "@/components/SuggestionPool"
import { Accordion } from "@/components/ui/accordion"
import { Skeleton } from "@/components/ui/skeleton"
import {
  HISTORY_CARD_ID,
  SUGGESTION_CARD_ID,
  useInterview,
} from "@/hooks/useInterview"

/** Compact strip placeholder shown after submit but before the `triage` event lands. */
function StripSkeleton() {
  return (
    <div className="flex gap-2 overflow-hidden" aria-label="Scoring diagnostic arms">
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="flex w-40 shrink-0 flex-col items-center gap-2 rounded-xl border border-border bg-card px-3 py-3"
        >
          <Skeleton className="size-12 rounded-full" />
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

  const busy =
    iv.status.kind === "scoring" ||
    iv.status.kind === "generating" ||
    iv.status.kind === "rescoring"
  const generating = iv.status.kind === "generating"

  // The arm whose full question detail is expanded inline below the strip.
  const detailArm = iv.arms.find((a) => a.name === iv.selectedArm)

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
            {/* 1. Differential strip (or loading skeleton before arms arrive). */}
            {iv.arms.length === 0 ? (
              <StripSkeleton />
            ) : (
              <DifferentialStrip
                arms={iv.arms}
                recentTransitions={iv.recentTransitions}
                leaderName={iv.leaderName}
                selectedArm={iv.selectedArm}
                onSelect={iv.selectArm}
              />
            )}

            {/* 2. Inline detail: the tapped arm's FULL question list (all questions,
                answered + unanswered), reusing DiagnosticArmCard in a one-item Accordion.
                Collapsing it (via the card's trigger) clears the selection. */}
            {detailArm && (
              <Accordion
                multiple
                value={[detailArm.name]}
                onValueChange={(value) => {
                  if (!(value as string[]).includes(detailArm.name)) {
                    iv.selectArm(detailArm.name) // toggles selection back off
                  }
                }}
              >
                <DiagnosticArmCard
                  arm={detailArm}
                  isLeader={detailArm.name === iv.leaderName}
                  transition={iv.recentTransitions[detailArm.name]}
                  generating={generating}
                  expanding={iv.expandingArms.has(detailArm.name)}
                  submitting={iv.submittingArm === detailArm.name}
                  busy={busy}
                  onAnswerBatch={iv.answerBatch}
                />
              </Accordion>
            )}

            {/* 3. General History card (unchanged surface). */}
            {iv.historyChecklist && (
              <HistoryCard
                checklist={iv.historyChecklist}
                answeredHistory={iv.answeredHistory}
                submitting={iv.submittingArm === HISTORY_CARD_ID}
                busy={busy}
                onAnswerBatch={iv.answerBatch}
              />
            )}

            {/* 4. Ranked suggestion pool — the primary "what to ask next" surface. */}
            <SuggestionPool
              suggestions={iv.suggestions}
              busy={busy}
              submitting={iv.submittingArm === SUGGESTION_CARD_ID}
              onAnswerBatch={iv.answerBatch}
            />

            {/* 5. Answered log (full width, the evolved Trace Viewer). */}
            <AnsweredLog entries={iv.answeredLog} />
          </>
        )}
      </main>
    </div>
  )
}
