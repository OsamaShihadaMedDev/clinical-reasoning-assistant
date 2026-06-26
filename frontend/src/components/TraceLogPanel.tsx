/**
 * TraceLogPanel — CLAUDE.md 6b's Agent Trace Viewer, now a real React component
 * (it replaces demo.html's hand-rendered trace log). It makes the feedback loop
 * visibly true: each answer that re-scores arms appends an entry showing the
 * triggering answer and every arm that moved (old → new, with the delta).
 *
 * Order matches demo.html: newest entry first; within an entry, biggest movers
 * first. It reads `ScoreTransition` records the backend already returns — no extra
 * backend state.
 */

import { ArrowDownRight, ArrowUpRight, History } from "lucide-react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { TraceEntry } from "@/hooks/useInterview"

export function TraceLogPanel({ entries }: { entries: TraceEntry[] }) {
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="size-4 text-brand" />
          Agent Trace Viewer
        </CardTitle>
        <CardDescription>
          Every re-score the feedback loop has made this session.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Answer a question to see arm scores change here.
          </p>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-border bg-muted/40 p-3"
            >
              <p className="mb-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">Answer: </span>
                {entry.answer}
              </p>
              {entry.transitions.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No arm scores changed.
                </p>
              ) : (
                <ul className="space-y-1">
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
