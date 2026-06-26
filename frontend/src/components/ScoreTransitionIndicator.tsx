/**
 * ScoreTransitionIndicator — the brief "old → new" overlay on a re-scored arm's
 * gauge (CLAUDE.md 6b component 4). Shows strikethrough old value, a direction
 * arrow, and the new value, then self-fades back to nothing after a couple of
 * seconds (opacity transition, ~300ms, ease-out — the single element animated per
 * score change).
 *
 * It self-manages its lifetime: a NEW transition object (the hook hands a fresh one
 * only for arms that actually moved this answer) re-triggers the show→fade cycle.
 */

import { useEffect, useState } from "react"
import { ArrowDownRight, ArrowUpRight } from "lucide-react"

import { cn } from "@/lib/utils"
import type { ScoreTransition } from "@/types"

const HOLD_MS = 2500
const FADE_MS = 350

export function ScoreTransitionIndicator({
  transition,
}: {
  transition: ScoreTransition | undefined
}) {
  const [shown, setShown] = useState<ScoreTransition | null>(null)
  const [fading, setFading] = useState(false)

  useEffect(() => {
    if (!transition) return
    setShown(transition)
    setFading(false)
    const holdTimer = setTimeout(() => setFading(true), HOLD_MS)
    const clearTimer = setTimeout(() => setShown(null), HOLD_MS + FADE_MS)
    return () => {
      clearTimeout(holdTimer)
      clearTimeout(clearTimer)
    }
  }, [transition])

  if (!shown) return null

  const up = shown.new_score >= shown.old_score

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-xs font-medium tabular-nums shadow-sm transition-opacity ease-out",
        fading ? "opacity-0" : "opacity-100",
      )}
      style={{ transitionDuration: `${FADE_MS}ms` }}
    >
      <span className="text-muted-foreground line-through">
        {shown.old_score.toFixed(2)}
      </span>
      {up ? (
        <ArrowUpRight className="size-3 text-brand" />
      ) : (
        <ArrowDownRight className="size-3 text-flag" />
      )}
      <span className={up ? "text-brand" : "text-flag"}>
        {shown.new_score.toFixed(2)}
      </span>
    </span>
  )
}
