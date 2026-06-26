/**
 * App — wires the interview together. The ComplaintBar is a fixed element that
 * morphs hero → docked; once started, the page shows the diagnostic-arm Accordion
 * (controlled, multi-open, with leader auto-expand from useInterview) alongside the
 * Agent Trace Viewer. All data comes from the SSE stream and /api/answer — no mocks.
 */

import { useState } from "react"

import { ComplaintBar } from "@/components/ComplaintBar"
import { DiagnosticArmCard } from "@/components/DiagnosticArmCard"
import { TraceLogPanel } from "@/components/TraceLogPanel"
import { Accordion } from "@/components/ui/accordion"
import { Skeleton } from "@/components/ui/skeleton"
import { useInterview } from "@/hooks/useInterview"

/** Placeholder cards shown after submit but before the `triage` event lands. */
function ScoringSkeletons() {
  return (
    <div className="flex flex-col gap-3" aria-label="Scoring diagnostic arms">
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 ring-1 ring-foreground/5"
        >
          <Skeleton className="size-[60px] rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-20" />
          </div>
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
        className="mx-auto max-w-6xl px-4 pb-24 transition-[padding] duration-500 ease-out"
        style={{ paddingTop: iv.started ? barHeight + 24 : 0 }}
      >
        {iv.started && (
          <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
            <section aria-label="Diagnostic arms">
              {iv.arms.length === 0 ? (
                <ScoringSkeletons />
              ) : (
                <Accordion
                  multiple
                  value={iv.openArms}
                  onValueChange={(value) => {
                    const next = value as string[]
                    // Arms opened by THIS toggle that weren't open before. Any such arm
                    // with no questions yet gets lazily generated (top-N fan-out skipped
                    // it); expandArm guards the rest, so firing it broadly is safe.
                    const newlyOpened = next.filter((n) => !iv.openArms.includes(n))
                    iv.setOpenArms(next)
                    newlyOpened.forEach((n) => iv.expandArm(n))
                  }}
                  className="flex flex-col gap-3"
                >
                  {iv.arms.map((arm) => (
                    <DiagnosticArmCard
                      key={arm.name}
                      arm={arm}
                      isLeader={arm.name === iv.leaderName}
                      transition={iv.recentTransitions[arm.name]}
                      generating={generating}
                      expanding={iv.expandingArms.has(arm.name)}
                      answeringId={iv.answeringId}
                      busy={busy}
                      onAnswer={iv.answer}
                    />
                  ))}
                </Accordion>
              )}
            </section>

            <aside className="lg:sticky" style={{ top: barHeight + 24 }}>
              <TraceLogPanel entries={iv.traceLog} />
            </aside>
          </div>
        )}
      </main>
    </div>
  )
}
