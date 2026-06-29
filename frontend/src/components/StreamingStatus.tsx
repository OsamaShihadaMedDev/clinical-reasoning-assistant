/**
 * StreamingStatus — the small "Live Data"-style status chip that lives by the docked
 * bar. It mirrors the real SSE sequence from /api/triage/stream
 * (scoring → generating(n of total) → ready), the re-scoring round-trip, and a clean
 * error state — so the user can see the agent loop actually progressing.
 */

import { Check, LoaderCircle, TriangleAlert } from "lucide-react"

import { cn } from "@/lib/utils"
import type { StreamStatus } from "@/hooks/useInterview"

/** A small pulsing dot for the active (in-flight) states. */
function LiveDot() {
  return (
    <span className="relative flex size-2">
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand-secondary opacity-75" />
      <span className="relative inline-flex size-2 rounded-full bg-brand" />
    </span>
  )
}

export function StreamingStatus({
  status,
  className,
}: {
  status: StreamStatus
  className?: string
}) {
  if (status.kind === "idle") return null

  let content: React.ReactNode
  let tone = "text-muted-foreground"

  switch (status.kind) {
    case "scoring":
      content = (
        <>
          <LiveDot />
          Scoring complaint…
        </>
      )
      break
    case "generating":
      content = (
        <>
          <LoaderCircle className="size-3.5 animate-spin text-brand" />
          {status.current
            ? `Generating questions… ${status.current} (${status.filled} of ${status.total})`
            : `Generating questions… (0 of ${status.total})`}
        </>
      )
      break
    case "rescoring": {
      // Distinct sub-label per SSE stage of the answer / custom-arm stream.
      const stageLabel =
        status.stage === "adding_arms"
          ? "Adding diagnoses…"
          : status.stage === "rescored"
            ? "Updating differential…"
            : status.stage === "ranking_suggestions"
              ? "Ranking next questions…"
              : "Re-scoring arms…"
      content = (
        <>
          <LoaderCircle className="size-3.5 animate-spin text-brand" />
          {stageLabel}
        </>
      )
      break
    }
    case "ready":
      content = (
        <>
          <Check className="size-3.5 text-brand" />
          Ready
        </>
      )
      tone = "text-brand"
      break
    case "error":
      content = (
        <>
          <TriangleAlert className="size-3.5 text-flag" />
          {status.detail}
        </>
      )
      tone = "text-flag"
      break
  }

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium tabular-nums",
        tone,
        className,
      )}
      role="status"
      aria-live="polite"
    >
      {content}
    </div>
  )
}
