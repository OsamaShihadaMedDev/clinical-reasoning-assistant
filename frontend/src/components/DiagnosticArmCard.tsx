/**
 * DiagnosticArmCard — one diagnostic arm as a card-styled Accordion item.
 *
 * Collapsed: name, the circular ScoreGauge, a status indicator (active vs.
 * deprioritized — distinguished by icon + label, not colour alone), a "Leading"
 * badge for the current top arm, a red-flag badge when the prioritisation agent's
 * reasoning carries a can't-miss tell, and the transient old→new score indicator.
 *
 * Expanded: the score `reasoning`, then the arm's questions (or sized Skeletons
 * while that arm's `arm_questions` SSE event is still pending).
 *
 * Open/closed is controlled by the parent Accordion (by arm name); this component
 * is purely presentational — the leader auto-expand logic lives in useInterview.
 */

import { useState } from "react"
import {
  Activity,
  Check,
  CircleDashed,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
} from "lucide-react"

import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { QuestionRow } from "@/components/QuestionRow"
import { ScoreGauge } from "@/components/ScoreGauge"
import { ScoreTransitionIndicator } from "@/components/ScoreTransitionIndicator"
import { cn } from "@/lib/utils"
import type { DiagnosticArm, ScoreTransition } from "@/types"

/** The prioritisation agent flags a can't-miss arm in its reasoning text rather
 *  than by inflating the score (CLAUDE.md Section 7); surface that tell. */
function isRedFlagged(reasoning: string): boolean {
  return /cannot be excluded|red flag|can't-miss|cant-miss/i.test(reasoning)
}

interface DiagnosticArmCardProps {
  arm: DiagnosticArm
  isLeader: boolean
  transition: ScoreTransition | undefined
  /** Questions are still streaming in at initial triage (show skeletons for empty
   *  active arms). */
  generating: boolean
  /** This specific arm's questions are being lazily generated on demand because the
   *  user just expanded an arm the top-N fan-out skipped (show skeletons for it). */
  expanding: boolean
  /** This card's batch submit is currently in flight (drives the submit button's
   *  loading state). */
  submitting: boolean
  busy: boolean
  /** Submit every drafted answer in this card together; returns whether it succeeded
   *  (so the card can clear the submitted drafts). */
  onAnswerBatch: (
    cardId: string,
    answers: { question_id: string; answer_text: string }[],
  ) => Promise<boolean>
}

export function DiagnosticArmCard({
  arm,
  isLeader,
  transition,
  generating,
  expanding,
  submitting,
  busy,
  onAnswerBatch,
}: DiagnosticArmCardProps) {
  // Drafts for this card's currently-unanswered questions: questionId -> text. Lives
  // here (not per row) so the single card-level submit can see across all rows.
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const flagged = isRedFlagged(arm.reasoning)
  const deprioritized = arm.status === "deprioritized"
  const awaitingQuestions = arm.questions.length === 0
  // Skeletons cover BOTH paths to questions: the initial top-N SSE fan-out
  // (`generating`) and on-demand lazy generation after the user expands this arm
  // (`expanding`).
  const showSkeletons =
    awaitingQuestions && !deprioritized && (generating || expanding)

  // The drafts with real (non-empty) text, ready to submit. A clinician may fill only
  // some rows, so empty/untouched ones are skipped.
  const pendingAnswers = Object.entries(drafts)
    .map(([question_id, value]) => ({ question_id, answer_text: value.trim() }))
    .filter((a) => a.answer_text.length > 0)
  const hasUnanswered = arm.questions.some((q) => !q.answered)
  const canSubmit = pendingAnswers.length > 0 && !busy

  function handleDraftChange(questionId: string, value: string) {
    setDrafts((d) => ({ ...d, [questionId]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    const submitted = pendingAnswers
    const ok = await onAnswerBatch(arm.name, submitted)
    if (ok) {
      // Clear only the drafts we actually submitted, leaving any half-typed rows alone.
      setDrafts((d) => {
        const next = { ...d }
        for (const a of submitted) delete next[a.question_id]
        return next
      })
    }
  }

  return (
    <AccordionItem
      value={arm.name}
      className={cn(
        "rounded-xl border border-border bg-card px-4 ring-1 ring-foreground/5 transition-opacity",
        deprioritized && "opacity-60",
      )}
    >
      <AccordionTrigger className="items-center gap-3 py-3 hover:no-underline">
        <ScoreGauge value={arm.relevance_score} />

        <div className="flex min-w-0 flex-col items-start gap-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-heading text-base font-medium text-foreground">
              {arm.name}
            </span>
            {isLeader && (
              <Badge className="gap-1">
                <Sparkles />
                Leading
              </Badge>
            )}
            {flagged && (
              <Badge variant="destructive" className="gap-1">
                <TriangleAlert />
                Red flag
              </Badge>
            )}
          </div>

          {/* Status: never colour-only — icon + label both. */}
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            {deprioritized ? (
              <>
                <CircleDashed className="size-3" />
                Deprioritized
              </>
            ) : (
              <>
                <Activity className="size-3 text-brand-secondary" />
                Active
              </>
            )}
          </span>
        </div>

        <span className="ml-auto mr-1 flex items-center">
          <ScoreTransitionIndicator transition={transition} />
        </span>
      </AccordionTrigger>

      <AccordionContent className="space-y-3">
        <p
          className={cn(
            "rounded-lg bg-muted/60 px-3 py-2 text-sm leading-relaxed",
            flagged ? "text-flag" : "text-secondary-foreground",
          )}
        >
          {arm.reasoning}
        </p>

        {showSkeletons ? (
          <div className="space-y-2" aria-label="Generating questions">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="space-y-2 rounded-lg border border-border bg-card px-3 py-2.5"
              >
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-3 w-3/5" />
                <Skeleton className="h-8 w-full" />
              </div>
            ))}
          </div>
        ) : awaitingQuestions ? (
          <p className="px-1 text-xs text-muted-foreground">
            No questions generated for this arm.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-2">
            {arm.questions.map((q) => (
              <QuestionRow
                key={q.id}
                question={q}
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
        )}
      </AccordionContent>
    </AccordionItem>
  )
}
