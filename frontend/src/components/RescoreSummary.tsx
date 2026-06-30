/**
 * RescoreSummary — ONE current snapshot of what the most recent re-score moved, and why.
 *
 * This replaces the old behaviour where AnsweredLog re-printed the full per-arm score
 * table under every answered question (so a 3-question batch showed the same table three
 * times). Scores now live here, once, summarising only the LATEST re-score; AnsweredLog
 * is a pure Q&A transcript again.
 *
 * Last-re-score-only, by design: `recentTransitions` is recomputed fresh on every
 * `onRescored` (it's a Record<arm_name, ScoreTransition> for the most recent batch only),
 * so re-running Re-score REPLACES this content rather than appending. Cumulative
 * since-session-start summaries are explicitly out of scope.
 *
 * No new backend data: it reads `recentTransitions` (already passed into DifferentialGrid
 * and OpenArmsLane) and each arm's CURRENT `.reasoning` (already on DiagnosticArm, already
 * current as of the latest re-score). The one-line reasoning excerpt below is a UI-only
 * trim — the full reasoning stays visible by opening that arm's card in the Open Cards
 * Lane, so this is intentionally a summary, not a duplicate of the full card.
 */

import { ArrowDownRight, ArrowUpRight, TrendingUp } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { RESCORE_SUMMARY_THRESHOLD } from "@/constants"
import { cn } from "@/lib/utils"
import type { DiagnosticArm, ScoreTransition } from "@/types"

interface RescoreSummaryProps {
  recentTransitions: Record<string, ScoreTransition>
  /** For looking up each moved arm's CURRENT .reasoning (to derive the one-line excerpt). */
  arms: DiagnosticArm[]
}

// Fallback truncation length when an arm's reasoning has no concise first sentence — also
// the "reasonable range" cap on how far in we'll accept a ". " as the first-sentence break.
const EXCERPT_LIMIT = 120

/** A one-line excerpt of an arm's reasoning for the compact summary row: the first
 *  sentence (everything before the first ". "), or — if there's no period within a
 *  reasonable range — the string truncated at the last word boundary before EXCERPT_LIMIT.
 *  UI-only; the full reasoning remains on the arm's open card. */
function reasoningExcerpt(reasoning: string): string {
  const trimmed = reasoning.trim()
  const breakIdx = trimmed.indexOf(". ")
  if (breakIdx !== -1 && breakIdx <= EXCERPT_LIMIT) {
    return trimmed.slice(0, breakIdx) // first sentence, without the trailing period-space
  }
  if (trimmed.length <= EXCERPT_LIMIT) return trimmed
  const slice = trimmed.slice(0, EXCERPT_LIMIT)
  const lastSpace = slice.lastIndexOf(" ")
  return `${(lastSpace > 0 ? slice.slice(0, lastSpace) : slice).trimEnd()}…`
}

export function RescoreSummary({ recentTransitions, arms }: RescoreSummaryProps) {
  // Nothing to summarise before the first re-score — the component simply doesn't exist
  // yet (same as the investigation pane before its first trigger), no empty-state card.
  if (Object.keys(recentTransitions).length === 0) return null

  // Only movements past the noise floor, biggest first. Same sort AnsweredLog used to do.
  const shown = Object.values(recentTransitions)
    .filter(
      (t) => Math.abs(t.new_score - t.old_score) >= RESCORE_SUMMARY_THRESHOLD,
    )
    .sort(
      (a, b) =>
        Math.abs(b.new_score - b.old_score) - Math.abs(a.new_score - a.old_score),
    )

  const reasoningByArm = new Map(arms.map((a) => [a.name, a.reasoning]))

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TrendingUp className="size-4 text-brand" />
          Latest re-score
        </CardTitle>
        <CardDescription>What moved in the most recent re-score.</CardDescription>
      </CardHeader>
      <CardContent>
        {shown.length === 0 ? (
          // A real re-score ran but nothing crossed the threshold — confirm it ran rather
          // than rendering nothing, since the clinician just clicked Re-score.
          <p className="text-sm text-muted-foreground">Scores held steady this round.</p>
        ) : (
          <ul className="space-y-2.5">
            {shown.map((t) => {
              const delta = t.new_score - t.old_score
              const up = delta >= 0
              const reasoning = reasoningByArm.get(t.arm_name)
              const excerpt = reasoning ? reasoningExcerpt(reasoning) : ""
              return (
                <li key={t.arm_name} className="space-y-0.5">
                  <div className="flex items-center justify-between gap-2 text-sm tabular-nums">
                    <span className="min-w-0 truncate font-medium text-foreground">
                      {t.arm_name}
                    </span>
                    <span
                      className={cn(
                        "inline-flex shrink-0 items-center gap-1 font-medium",
                        up ? "text-brand" : "text-flag",
                      )}
                    >
                      {t.old_score.toFixed(2)}
                      {up ? (
                        <ArrowUpRight className="size-3.5" />
                      ) : (
                        <ArrowDownRight className="size-3.5" />
                      )}
                      {t.new_score.toFixed(2)}
                      <span className="text-xs opacity-80">
                        ({delta >= 0 ? "+" : ""}
                        {delta.toFixed(2)})
                      </span>
                    </span>
                  </div>
                  {excerpt && (
                    <p className="truncate text-xs font-light text-muted-foreground">
                      {excerpt}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
