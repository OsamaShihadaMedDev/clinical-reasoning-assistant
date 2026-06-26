/**
 * QuestionRow — one history-taking question inside an expanded arm. The question
 * text leads; `diagnostic_intent` is supporting/secondary text (CLAUDE.md Section 3:
 * every question shows *why* it's asked, but it must not compete visually with the
 * question itself).
 *
 * Two clearly distinct states (ux-guidelines: answered/unanswered must not look
 * near-identical): unanswered shows an answer field + submit; answered renders as a
 * settled, read-only row with the captured answer.
 */

import { useState } from "react"
import { Check, CircleCheck, LoaderCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { ClinicalQuestion } from "@/types"

interface QuestionRowProps {
  question: ClinicalQuestion
  submitting: boolean
  /** True while ANY answer on the interview is in flight (re-scoring is global). */
  busy: boolean
  onAnswer: (questionId: string, answerText: string) => void
}

export function QuestionRow({
  question,
  submitting,
  busy,
  onAnswer,
}: QuestionRowProps) {
  const [value, setValue] = useState("")

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

  const canSubmit = value.trim().length > 0 && !busy

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <p className="text-sm font-medium text-foreground">{question.text}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {question.diagnostic_intent}
      </p>
      <form
        className="mt-2 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) onAnswer(question.id, value.trim())
        }}
      >
        <Input
          value={value}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setValue(e.target.value)
          }
          placeholder="Type the patient's answer…"
          disabled={busy}
          aria-label={`Answer for: ${question.text}`}
          className="h-8"
        />
        <Button type="submit" size="sm" disabled={!canSubmit} className="cursor-pointer">
          {submitting ? (
            <>
              <LoaderCircle className="animate-spin" />
              Re-scoring
            </>
          ) : (
            <>
              <Check />
              Submit
            </>
          )}
        </Button>
      </form>
    </div>
  )
}
