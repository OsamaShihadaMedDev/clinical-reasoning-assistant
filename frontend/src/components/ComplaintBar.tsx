/**
 * ComplaintBar — the chief-complaint input in its two states (CLAUDE.md Section 5).
 *
 * Hero (nothing submitted): a two-pane split, vertically centred as a whole — a LEFT
 * column (badge, heading, subtitle, the inputs + submit) beside a RIGHT showcase column
 * (example-complaint chips + a static "what you'll see" preview). At lg+ it is a fixed,
 * vertically-centred overlay that fits one screen; on narrow viewports the panes stack
 * AND the hero sits in normal document flow (not fixed) so the page scrolls and the
 * stacked content stays reachable — a fixed overlay can't scroll. Docked (after submit):
 * the SAME inputs shrink into a persistent top bar and the showcase column drops away.
 *
 * The inputs are never unmounted/remounted between states (CLAUDE.md §12.6): the form
 * lives inside an ALWAYS-rendered left-column wrapper, so only its container's
 * transform/styling animates between hero and docked — it reads as one element moving
 * up, not two elements swapping (ux-guidelines row 13: animate transform, not top/width,
 * for the primary motion). The hero heading/subtitle and the right showcase column are
 * decorative and are allowed to drop on dock.
 */

import { useEffect, useRef, useState } from "react"
import { BrainCircuit, FlaskConical, LoaderCircle, Stethoscope } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { GlobalRescoreButton } from "@/components/GlobalRescoreButton"
import { ScoreGauge } from "@/components/ScoreGauge"
import { StreamingStatus } from "@/components/StreamingStatus"
import { cn } from "@/lib/utils"
import type { StreamStatus } from "@/hooks/useInterview"
import type { DiagnosticArm, InvestigationSuggestion } from "@/types"

/** Hero-only example complaints — populate both inputs on click so a visitor can see
 *  real output in one click rather than typing a case from scratch. Deliberately a
 *  SMALL, varied set (not an exhaustive list) so the row stays a single line and
 *  doesn't turn into its own competing UI element. */
const EXAMPLE_COMPLAINTS: { complaint: string; context: string }[] = [
  { complaint: "chest pain", context: "62-year-old male, smoker, pain worse on exertion" },
  { complaint: "abdominal pain", context: "29-year-old female, lower right quadrant, 2 days" },
  { complaint: "headache with fever", context: "34-year-old male, 3 days, neck stiffness" },
  { complaint: "shortness of breath", context: "45-year-old female, gradual onset, 2 weeks" },
]

/** Static, non-interactive preview data — illustrates real output shape using real
 *  component primitives (ScoreGauge, the investigation card layout). NOT connected to
 *  any live session; these numbers never change. Field shapes match DiagnosticArm /
 *  InvestigationSuggestion from "@/types" but only the fields this preview actually
 *  renders are populated — this is presentation data, not a fake session object. */
const MOCK_PREVIEW_ARMS: Pick<DiagnosticArm, "name" | "relevance_score">[] = [
  { name: "Pulmonary Embolism", relevance_score: 0.62 },
  { name: "Pneumothorax", relevance_score: 0.41 },
  { name: "Musculoskeletal", relevance_score: 0.18 },
]

const MOCK_PREVIEW_INVESTIGATION: Pick<
  InvestigationSuggestion,
  "name" | "reasoning" | "arm_name"
> = {
  name: "CT pulmonary angiography",
  reasoning: "Direct imaging to confirm or exclude PE given current likelihood.",
  arm_name: "Pulmonary Embolism",
}

interface ComplaintBarProps {
  docked: boolean
  busy: boolean
  status: StreamStatus
  onStart: (chiefComplaint: string, patientContext: string) => void
  /** Reports the bar's measured height so the page can reserve top padding and
   *  never hide arm cards behind the fixed bar (whatever it wraps to). */
  onHeightChange?: (height: number) => void
  /** Pixels to push the bar down from the top when docked, so it clears the page-wide
   *  disclaimer banner (App.tsx) that sits above it. Only applied in the docked (fixed
   *  top) state; the hero already clears the banner via its 28vh offset / mobile padding. */
  topOffset?: number
  /** Global "Re-score" control (anchored here, beside the status chip): pending draft
   *  count across the page, its in-flight flag, and the submit-all handler. */
  pendingDraftCount: number
  rescoreSubmitting: boolean
  onRescoreAll: () => void
  /** On-demand "Suggest workup" control (anchored beside Re-score): its in-flight flag and
   *  the handler that requests a fresh investigation snapshot. Same prop-drilling pattern as
   *  onRescoreAll, but a visually distinct (outline) button — it is not a re-score twin. */
  investigationsLoading: boolean
  onSuggestInvestigations: () => void
}

export function ComplaintBar({
  docked,
  busy,
  status,
  onStart,
  onHeightChange,
  topOffset = 0,
  pendingDraftCount,
  rescoreSubmitting,
  onRescoreAll,
  investigationsLoading,
  onSuggestInvestigations,
}: ComplaintBarProps) {
  const [chiefComplaint, setChiefComplaint] = useState("")
  const [patientContext, setPatientContext] = useState("")

  const innerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = innerRef.current
    if (!node || !onHeightChange) return
    const report = () => onHeightChange(node.getBoundingClientRect().height)
    report()
    const observer = new ResizeObserver(report)
    observer.observe(node)
    return () => observer.disconnect()
  }, [onHeightChange])

  const canSubmit = chiefComplaint.trim().length > 0 && !busy

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (canSubmit) onStart(chiefComplaint.trim(), patientContext.trim())
  }

  return (
    <div
      // Docked only: push the fixed bar below the disclaimer banner (App.tsx). Inline
      // `top` overrides the `top-0` class; the hero states need no offset (28vh / mobile
      // padding already clear the banner), so leave their positioning untouched.
      style={docked ? { top: topOffset } : undefined}
      className={cn(
        "z-30 origin-top will-change-transform transition-transform duration-500 ease-out",
        docked
          ? "fixed inset-x-0 top-0 translate-y-0"
          : // Hero: in normal document flow on mobile (so the page scrolls and the stacked
            // panes stay reachable — a fixed overlay can't scroll), but a fixed, vertically
            // offset overlay at lg+ where the two-pane content fits one screen. Keeping
            // fixed + translate-y at lg preserves the transform-driven dock slide (§12.6);
            // on mobile the dock becomes a position swap, the accepted cost of scrollability.
            "relative py-12 lg:fixed lg:inset-x-0 lg:top-0 lg:translate-y-[28vh] lg:py-0",
      )}
    >
      <div
        ref={innerRef}
        className={cn(
          "mx-auto w-full px-4 transition-[max-width] duration-500 ease-out",
          docked
            ? "max-w-6xl"
            : "flex max-w-5xl flex-col items-center gap-8 lg:flex-row lg:items-center lg:gap-12",
        )}
      >
        {/* LEFT PANE — functionality column. ALWAYS rendered (NOT gated on !docked) so the
            shared form below never unmounts/remounts across hero↔docked; only its
            container styling/transform animates (CLAUDE.md §12.6 + this file's docstring).
            In docked it is a transparent full-width pass-through (the bar); in hero it is
            the left half of the two-pane split. */}
        <div className={cn(docked ? "w-full" : "w-full max-w-md lg:flex-1")}>
          {!docked && (
            <>
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-brand">
                <BrainCircuit className="size-3.5" />
                Clinical Reasoning Assistant
              </div>
              <h1 className="font-heading text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
                What's the chief complaint?
              </h1>
              <p className="mt-2 max-w-md text-sm text-muted-foreground">
                Assists targeted history-taking by diagnostic arm. It does not
                diagnose — the clinician decides.
              </p>
            </>
          )}

          <div
            className={cn(
              "rounded-2xl transition-all duration-500 ease-out",
              docked
                ? "border border-border bg-background/85 px-4 py-3 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70"
                : "mt-6 border border-transparent",
            )}
          >
            <form
              onSubmit={handleSubmit}
              className={cn(
                "flex gap-3",
                docked ? "flex-row flex-wrap items-end" : "flex-col",
              )}
            >
              {docked && (
                <Stethoscope className="mb-1.5 hidden size-5 shrink-0 text-brand sm:block" />
              )}

              <div className={cn("flex flex-col gap-1", docked ? "min-w-[180px] flex-1" : "")}>
                {!docked && (
                  <label htmlFor="chief-complaint" className="sr-only">
                    Chief complaint
                  </label>
                )}
                <Textarea
                  id="chief-complaint"
                  value={chiefComplaint}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                    setChiefComplaint(e.target.value)
                  }
                  placeholder="e.g. chest pain"
                  aria-label="Chief complaint"
                  rows={1}
                  className={cn(
                    "resize-none",
                    docked
                      ? "min-h-9 py-1.5 text-sm"
                      : "min-h-[72px] rounded-xl text-lg",
                  )}
                />
              </div>

              <div className={cn("flex flex-col gap-1", docked ? "min-w-[200px] flex-[2]" : "")}>
                {!docked && (
                  <label htmlFor="patient-context" className="sr-only">
                    Patient context
                  </label>
                )}
                <Input
                  id="patient-context"
                  value={patientContext}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                    setPatientContext(e.target.value)
                  }
                  placeholder="Patient context — age, sex, risk factors…"
                  aria-label="Patient context"
                  className={cn(docked ? "h-9" : "h-11 rounded-xl text-base")}
                />
              </div>

              <Button
                type="submit"
                size={docked ? "default" : "lg"}
                disabled={!canSubmit}
                className={cn("cursor-pointer gap-1.5", docked ? "" : "h-11 px-6")}
              >
                <Stethoscope className={docked ? "size-4" : "size-4"} />
                {docked ? "Re-run" : "Start interview"}
              </Button>
            </form>

            {/* Rendered ONCE here, outside the docked conditional, so a hero-state submit
                failure is visible too (StreamingStatus returns null for idle/in the normal
                hero idle case, so this stays quiet until something actually fails). */}
            <StreamingStatus status={status} className="mt-2" />

            {docked && (
              <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  {/* On-demand workup snapshot. Distinct outline styling so it doesn't read
                      as a second Re-score; disabled while any stream is busy (don't snapshot
                      mid-re-score) or while its own request is in flight. */}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={onSuggestInvestigations}
                    disabled={busy || investigationsLoading}
                    className="cursor-pointer gap-1.5"
                  >
                    {investigationsLoading ? (
                      <>
                        <LoaderCircle className="animate-spin" />
                        Suggesting…
                      </>
                    ) : (
                      <>
                        <FlaskConical />
                        Suggest workup
                      </>
                    )}
                  </Button>
                  <GlobalRescoreButton
                    pendingCount={pendingDraftCount}
                    submitting={rescoreSubmitting}
                    busy={busy}
                    onRescore={onRescoreAll}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT PANE — showcase (hero only): example chips + the static "what you'll see"
            preview. Drops away on dock, same as the old header/preview blocks did. */}
        {!docked && (
          <div className="w-full max-w-md lg:flex-1">
            <p className="mb-2 text-xs font-medium text-muted-foreground">Try:</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_COMPLAINTS.map((ex) => (
                <Button
                  key={ex.complaint}
                  type="button"
                  variant="outline"
                  size="sm"
                  className="cursor-pointer rounded-full text-xs font-normal"
                  onClick={() => {
                    setChiefComplaint(ex.complaint)
                    setPatientContext(ex.context)
                  }}
                >
                  {ex.complaint}
                </Button>
              ))}
            </div>

            <div className="mt-6 rounded-2xl border border-dashed border-border bg-card/40 p-4">
              <p className="mb-3 text-center text-xs font-medium tracking-wide text-muted-foreground uppercase">
                What you'll see
              </p>
              {/* Single column: the right pane is capped near max-w-md, so a 2-up grid here
                  would cram the gauges against the card — stack the two sections instead. */}
              <div className="flex flex-col gap-4">
                {/* 3 mock differential tiles, smaller scale than the real grid */}
                <div>
                  <p className="mb-2 text-xs font-medium text-foreground">Live differential</p>
                  <div className="flex gap-2">
                    {MOCK_PREVIEW_ARMS.map((arm) => (
                      <div
                        key={arm.name}
                        className="flex flex-1 flex-col items-center gap-1 rounded-xl border border-border bg-background px-2 py-3"
                      >
                        <ScoreGauge value={arm.relevance_score} size={40} strokeWidth={4} />
                        <p className="text-center text-[11px] leading-tight font-medium text-foreground">
                          {arm.name}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* One mock investigation item, reusing the real card shape */}
                <div>
                  <p className="mb-2 text-xs font-medium text-foreground">On-demand workup suggestions</p>
                  <div className="rounded-lg border border-border bg-background px-3 py-2">
                    <p className="text-sm font-medium text-foreground">{MOCK_PREVIEW_INVESTIGATION.name}</p>
                    <p className="mt-0.5 text-xs font-light text-muted-foreground">
                      {MOCK_PREVIEW_INVESTIGATION.reasoning}
                    </p>
                    <Badge variant="secondary" className="mt-1.5 font-normal">
                      {MOCK_PREVIEW_INVESTIGATION.arm_name}
                    </Badge>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
