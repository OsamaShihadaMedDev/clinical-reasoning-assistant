/**
 * AnsweredLog — the chronological record of every answered question and the score
 * moves it caused. It REPLACES TraceLogPanel: same ScoreTransition delta rendering
 * (sorted by magnitude, up/down arrow, brand/flag colour — carried over verbatim
 * because it's correct), but keyed per ANSWERED QUESTION instead of per re-score batch,
 * and now showing the question + answer text as a transcript, not just the trigger.
 *
 * Ordering: NEWEST-FIRST, deliberately kept from TraceLogPanel — the most recent answer's
 * effect is what the clinician most wants to see, and it avoids a scroll-to-bottom on
 * every submit. (The "transcript / append-at-bottom" alternative was considered and
 * rejected for that reason.) The hook prepends new entries, so we render in order.
 */

import { ArrowDownRight, ArrowUpRight, History, ListChecks } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { AnsweredLogEntry } from "@/hooks/useInterview"

export function AnsweredLog({ entries }: { entries: AnsweredLogEntry[] }) {
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListChecks className="size-4 text-brand" />
          Answered log
        </CardTitle>
        <CardDescription>
          Every question answered this session and the arm scores it moved.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Answer a question to build the log — its effect on the differential shows here.
          </p>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-border bg-muted/40 p-3"
            >
              <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-foreground">
                {entry.questionText}
                {entry.isHistoryQuestion && (
                  <Badge variant="secondary" className="gap-1 font-normal">
                    <History className="size-3" />
                    History
                  </Badge>
                )}
              </p>
              <p className="mt-1 text-sm text-secondary-foreground">
                <span className="font-medium text-brand">Answer: </span>
                {entry.answerText}
              </p>

              {entry.transitions.length === 0 ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  No arm scores changed.
                </p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {[...entry.transitions]
                    .sort(
                      (a, b) =>
                        Math.abs(b.new_score - b.old_score) -
                        Math.abs(a.new_score - a.old_score),
                    )
                    .map((t) => {
                      const delta = t.new_score - t.old_score
                      const up = delta >= 0
                      return (
                        <li
                          key={t.arm_name}
                          className="flex items-center justify-between gap-2 text-sm tabular-nums"
                        >
                          <span className="min-w-0 truncate text-foreground">
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
                        </li>
                      )
                    })}
                </ul>
              )}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
