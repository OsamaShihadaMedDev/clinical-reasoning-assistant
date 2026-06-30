/**
 * ComplaintBar — the chief-complaint input in its two states (CLAUDE.md Section 5).
 *
 * Hero (nothing submitted): a large, vertically-centred input block on an otherwise
 * empty page. Docked (after submit): the SAME inputs shrink into a persistent top
 * bar. The inputs are never unmounted/remounted between states — only their
 * container's transform (translateY) and styling animate — so it reads as one
 * element moving up, not two elements swapping (ux-guidelines row 13: animate
 * transform, not top/width, for the primary motion). The big hero heading is
 * decorative and is allowed to drop on dock.
 */

import { useEffect, useRef, useState } from "react"
import { FlaskConical, LoaderCircle, Stethoscope } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { GlobalRescoreButton } from "@/components/GlobalRescoreButton"
import { StreamingStatus } from "@/components/StreamingStatus"
import { cn } from "@/lib/utils"
import type { StreamStatus } from "@/hooks/useInterview"

interface ComplaintBarProps {
  docked: boolean
  busy: boolean
  status: StreamStatus
  onStart: (chiefComplaint: string, patientContext: string) => void
  /** Reports the bar's measured height so the page can reserve top padding and
   *  never hide arm cards behind the fixed bar (whatever it wraps to). */
  onHeightChange?: (height: number) => void
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
  pendingDraftCount,
  rescoreSubmitting,
  onRescoreAll,
  investigationsLoading,
  onSuggestInvestigations,
}: ComplaintBarProps) {
  const [chiefComplaint, setChiefComplaint] = useState("chest pain")
  const [patientContext, setPatientContext] = useState(
    "62-year-old male, smoker, pain worse on exertion, radiates to left arm",
  )

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
      className={cn(
        "fixed inset-x-0 top-0 z-30 origin-top will-change-transform transition-transform duration-500 ease-out",
        docked ? "translate-y-0" : "translate-y-[28vh]",
      )}
    >
      <div
        ref={innerRef}
        className={cn(
          "mx-auto w-full px-4 transition-[max-width] duration-500 ease-out",
          docked ? "max-w-6xl" : "max-w-2xl",
        )}
      >
        {!docked && (
          <header className="mb-6 text-center">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-brand">
              <Stethoscope className="size-3.5" />
              Clinical Reasoning Assistant
            </div>
            <h1 className="font-heading text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              What's the chief complaint?
            </h1>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
              Assists targeted history-taking by diagnostic arm. It does not
              diagnose — the clinician decides.
            </p>
          </header>
        )}

        <div
          className={cn(
            "rounded-2xl transition-all duration-500 ease-out",
            docked
              ? "border border-border bg-background/85 px-4 py-3 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70"
              : "border border-transparent",
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

          {docked && (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <StreamingStatus status={status} />
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
    </div>
  )
}
