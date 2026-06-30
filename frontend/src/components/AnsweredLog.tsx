/**
 * AnsweredLog — the chronological record of every answered question. It REPLACES
 * TraceLogPanel: now a pure Q&A transcript (question + answer text), keyed per ANSWERED
 * QUESTION. The per-arm score moves it used to render moved to RescoreSummary, which
 * shows ONE current summary of the latest re-score instead of repeating the full table
 * under every single answered question.
 *
 * Ordering: NEWEST-FIRST, deliberately kept from TraceLogPanel — the most recent answer is
 * what the clinician most wants to see, and it avoids a scroll-to-bottom on every submit.
 * (The "transcript / append-at-bottom" alternative was considered and rejected for that
 * reason.) The hook prepends new entries, so we render in order.
 */

import { History, ListChecks } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
          Every question answered this session, for reference.
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
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
