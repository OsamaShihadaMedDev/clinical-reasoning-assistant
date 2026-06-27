/**
 * HistoryCard — the General History card (History Agent). It renders the population's
 * general-history checklist ABOVE the diagnostic arms.
 *
 * Deliberately NOT an arm card: no ScoreGauge / relevance ring, because these
 * background questions (past medical history, meds, smoking, …) aren't weighed against
 * each other the way diagnostic arms are. It reuses the arm cards' question visual
 * language AND their card-level-submit pattern: the clinician fills several rows, then
 * one "Submit answers" button sends them together as a batch (one re-score).
 *
 * When `assumed_default` is true (classification fell back to adult_general for lack of
 * context), it shows an inline assumption note using `category_reasoning` verbatim,
 * pointing the user at the existing docked "Re-run" button as the correction path (no
 * new button, no blocking modal). Submissions flow through the same `onAnswerBatch` the
 * arm cards use; the backend routes them as HistoryAnswers by id, and the re-score lands
 * in the Trace Viewer exactly like an arm answer.
 */

import { useState } from "react"
import { Check, CircleCheck, ClipboardList, Info, LoaderCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { HISTORY_CARD_ID } from "@/hooks/useInterview"
import type { HistoryChecklist, HistoryQuestion, PatientCategory } from "@/types"

/** Human-readable population labels for the small category badge. */
const CATEGORY_LABELS: Record<PatientCategory, string> = {
  pediatric: "Pediatric",
  ob_gyn: "OB/GYN",
  surgical: "Surgical",
  geriatric: "Geriatric",
  adult_general: "Adult — general",
}

interface HistoryCardProps {
  checklist: HistoryChecklist
  /** Map of answered history question id -> the captured answer text. */
  answeredHistory: Record<string, string>
  /** This card's batch submit is in flight (drives the submit button's loading state). */
  submitting: boolean
  /** True while ANY answer is in flight or the stream is still settling — disables
   *  inputs/submission (the session id only exists once the stream finishes). */
  busy: boolean
  onAnswerBatch: (
    cardId: string,
    answers: { question_id: string; answer_text: string }[],
  ) => Promise<boolean>
}

export function HistoryCard({
  checklist,
  answeredHistory,
  submitting,
  busy,
  onAnswerBatch,
}: HistoryCardProps) {
  // Drafts for the currently-unanswered questions: questionId -> text.
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  // The empty-context reasoning already tells the user to re-run; only append the
  // guidance when the reasoning doesn't already mention it, so it never duplicates.
  const mentionsRerun = /re-?run/i.test(checklist.category_reasoning)

  const pendingAnswers = Object.entries(drafts)
    .map(([question_id, value]) => ({ question_id, answer_text: value.trim() }))
    .filter((a) => a.answer_text.length > 0)
  const hasUnanswered = checklist.questions.some(
    (q) => answeredHistory[q.id] === undefined,
  )
  const canSubmit = pendingAnswers.length > 0 && !busy

  function handleDraftChange(questionId: string, value: string) {
    setDrafts((d) => ({ ...d, [questionId]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    const submitted = pendingAnswers
    const ok = await onAnswerBatch(HISTORY_CARD_ID, submitted)
    if (ok) {
      setDrafts((d) => {
        const next = { ...d }
        for (const a of submitted) delete next[a.question_id]
        return next
      })
    }
  }

  return (
    <Card className="mb-3 gap-3">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <ClipboardList className="size-4 text-brand" />
          General History
          <Badge variant="secondary" className="font-normal">
            {CATEGORY_LABELS[checklist.category]}
          </Badge>
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-2">
        {checklist.assumed_default && (
          <div className="flex items-start gap-2 rounded-lg border border-brand/30 bg-brand/5 px-3 py-2 text-xs text-secondary-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0 text-brand" aria-hidden="true" />
            <p>
              {checklist.category_reasoning}
              {!mentionsRerun && (
                <>
                  {" "}
                  Add age, sex, or other details above and press{" "}
                  <span className="font-medium text-brand">Re-run</span> for a more
                  specific checklist.
                </>
              )}
            </p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-2">
          {checklist.questions.map((q) => (
            <HistoryQuestionRow
              key={q.id}
              question={q}
              answer={answeredHistory[q.id]}
              draftValue={drafts[q.id] ?? ""}
              busy={busy}
              onDraftChange={handleDraftChange}
            />
          ))}
          {hasUnanswered && (
            <div className="flex justify-end pt-0.5">
              <Button
                type="submit"
                size="sm"
                disabled={!canSubmit}
                className="cursor-pointer"
              >
                {submitting ? (
                  <>
                    <LoaderCircle className="animate-spin" />
                    Re-scoring
                  </>
                ) : (
                  <>
                    <Check />
                    Submit answers
                  </>
                )}
              </Button>
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  )
}

interface HistoryQuestionRowProps {
  question: HistoryQuestion
  /** The captured answer text if this question has been answered, else undefined. */
  answer: string | undefined
  /** Current draft text for this row, owned by the parent card. */
  draftValue: string
  busy: boolean
  onDraftChange: (questionId: string, value: string) => void
}

function HistoryQuestionRow({
  question,
  answer,
  draftValue,
  busy,
  onDraftChange,
}: HistoryQuestionRowProps) {
  if (answer !== undefined) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-border bg-secondary/60 px-3 py-2.5">
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">
            {question.question_text}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{question.rationale}</p>
          <p className="mt-1.5 text-sm text-secondary-foreground">
            <span className="font-medium text-brand">Answered: </span>
            {answer}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <p className="text-sm font-medium text-foreground">{question.question_text}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{question.rationale}</p>
      <Input
        value={draftValue}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          onDraftChange(question.id, e.target.value)
        }
        placeholder="Type the patient's answer…"
        disabled={busy}
        aria-label={`Answer for: ${question.question_text}`}
        className="mt-2 h-8"
      />
    </div>
  )
}
