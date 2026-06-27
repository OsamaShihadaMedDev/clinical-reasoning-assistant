/**
 * QuestionRow — one history-taking question inside an expanded arm. The question
 * text leads; `diagnostic_intent` is supporting/secondary text (CLAUDE.md Section 3:
 * every question shows *why* it's asked, but it must not compete visually with the
 * question itself).
 *
 * Submission is now CARD-LEVEL, not per-row: this row no longer owns a form or submit
 * button. Unanswered, it is a controlled input that reports its draft up to the parent
 * card via `onDraftChange`; the card holds all its rows' drafts and submits them
 * together with one button (so the re-score sees several new answers at once). The
 * answered branch (the settled, read-only rendering) is unchanged.
 */

import { CircleCheck } from "lucide-react"

import { Input } from "@/components/ui/input"
import type { ClinicalQuestion } from "@/types"

interface QuestionRowProps {
  question: ClinicalQuestion
  /** The current draft text for this row, owned by the parent card. */
  draftValue: string
  /** True while ANY answer on the interview is in flight (re-scoring is global). */
  busy: boolean
  onDraftChange: (questionId: string, value: string) => void
}

export function QuestionRow({
  question,
  draftValue,
  busy,
  onDraftChange,
}: QuestionRowProps) {
  if (question.answered) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-border bg-secondary/60 px-3 py-2.5">
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">{question.text}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {question.diagnostic_intent}
          </p>
          <p className="mt-1.5 text-sm text-secondary-foreground">
            <span className="font-medium text-brand">Answered: </span>
            {question.answer_text}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <p className="text-sm font-medium text-foreground">{question.text}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {question.diagnostic_intent}
      </p>
      <Input
        value={draftValue}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          onDraftChange(question.id, e.target.value)
        }
        placeholder="Type the patient's answer…"
        disabled={busy}
        aria-label={`Answer for: ${question.text}`}
        className="mt-2 h-8"
      />
    </div>
  )
}
