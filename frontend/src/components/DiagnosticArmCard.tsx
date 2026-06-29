/**
 * DiagnosticArmCard — one diagnostic arm's FULL detail card, the content of a slot in the
 * Open Cards Lane.
 *
 * It is no longer an Accordion item driven by a single-select toggle (that mechanism is
 * gone): it is unconditionally-rendered content inside whichever lane slot it occupies,
 * with an explicit close button in its header (calls `onClose`) in place of the old
 * expand/collapse chevron. Open/closed now means "is this arm in the lane", owned by
 * useInterview's openArms.
 *
 * Header: name, the circular ScoreGauge, a status indicator (active vs. deprioritized —
 * icon + label, never colour alone), a "Leading" badge for the top arm, a red-flag badge
 * when the prioritisation reasoning carries a can't-miss tell, the transient old->new
 * score indicator, and the close button.
 *
 * Body: the score `reasoning`, then the questions split into two visually distinct groups:
 *  - UNANSWERED questions stay full-weight (rationale + full-size input) — they are the
 *    only thing still asking for the clinician's action, so they keep full prominence and
 *    render FIRST (immediately visible without scrolling past completed work).
 *  - ANSWERED questions collapse to a single compact line each (question + answer, a small
 *    reused CircleCheck, no rationale, no card chrome) and sit at the BOTTOM as a settled
 *    record. (Order decision: actionable-first; see the two groups below.)
 * While an arm's questions are still being generated (initial top-N SSE fan-out or
 * on-demand lazy expand) it shows sized Skeletons instead.
 */

import {
  Activity,
  Check,
  CircleCheck,
  CircleDashed,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
  UserPlus,
  X,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { QuestionRow } from "@/components/QuestionRow"
import { ScoreGauge } from "@/components/ScoreGauge"
import { ScoreTransitionIndicator } from "@/components/ScoreTransitionIndicator"
import { isRedFlagged } from "@/lib/clinical"
import { cn } from "@/lib/utils"
import type { DiagnosticArm, ScoreTransition } from "@/types"

interface DiagnosticArmCardProps {
  arm: DiagnosticArm
  isLeader: boolean
  transition: ScoreTransition | undefined
  /** Questions are still streaming in at initial triage (show skeletons for empty
   *  active arms). */
  generating: boolean
  /** This specific arm's questions are being lazily generated on demand because the
   *  user just opened an arm the top-N fan-out skipped (show skeletons for it). */
  expanding: boolean
  /** This card's batch submit is currently in flight (drives the submit button's
   *  loading state). */
  submitting: boolean
  /** This arm's score is mid-recalculation (any answer's re-score window) — pulse the
   *  gauge. Independent of `submitting`: every active arm re-scores, not just this card. */
  rescoring: boolean
  busy: boolean
  /** Submit every drafted answer in this card together; returns whether it succeeded
   *  (so the card can clear the submitted drafts). */
  onAnswerBatch: (
    cardId: string,
    answers: { question_id: string; answer_text: string }[],
  ) => Promise<boolean>
  /** Remove this arm from the lane (the header close affordance). */
  onClose: (armName: string) => void
  /** Shared global draft store (keyed by question_id) and its writer — this card reads/
   *  writes its own questions' drafts here instead of owning local state, so the global
   *  Re-score control can see them. */
  drafts: Record<string, string>
  onDraftChange: (questionId: string, text: string) => void
  /** Clear the given ids from the shared store (called on this card's own submit only). */
  onClearDrafts: (ids: string[]) => void
  /** Total non-empty pending drafts across the WHOLE page — used to detect whether any
   *  draft exists OUTSIDE this card (count > this card's own pending) for the nudge text. */
  pendingDraftCount: number
}

export function DiagnosticArmCard({
  arm,
  isLeader,
  transition,
  generating,
  expanding,
  submitting,
  rescoring,
  busy,
  onAnswerBatch,
  onClose,
  drafts,
  onDraftChange,
  onClearDrafts,
  pendingDraftCount,
}: DiagnosticArmCardProps) {
  const flagged = isRedFlagged(arm.reasoning)
  const deprioritized = arm.status === "deprioritized"
  const awaitingQuestions = arm.questions.length === 0
  // Skeletons cover BOTH paths to questions: the initial top-N SSE fan-out
  // (`generating`) and on-demand lazy generation after the user opens this arm
  // (`expanding`).
  const showSkeletons =
    awaitingQuestions && !deprioritized && (generating || expanding)

  // Split answered vs. unanswered: unanswered keep full weight and lead; answered are
  // compacted to a one-line record at the bottom.
  const unanswered = arm.questions.filter((q) => !q.answered)
  const answered = arm.questions.filter((q) => q.answered)

  // This card's own pending answers: its question ids with non-empty text in the SHARED
  // store. Iterating own ids (not all of `drafts`) scopes the per-card submit to just this
  // card. A clinician may fill only some rows, so empty/untouched ones are skipped.
  const pendingAnswers = arm.questions
    .map((q) => ({ question_id: q.id, answer_text: (drafts[q.id] ?? "").trim() }))
    .filter((a) => a.answer_text.length > 0)
  const canSubmit = pendingAnswers.length > 0 && !busy
  // A non-empty draft exists somewhere OTHER than this card — disambiguates that this
  // button submits only this card, not the whole page (the global control does that).
  const hasOtherPendingDrafts = pendingDraftCount > pendingAnswers.length

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    const submitted = pendingAnswers
    const ok = await onAnswerBatch(arm.name, submitted)
    // Clear only the ids we submitted — never any other card's pending drafts.
    if (ok) onClearDrafts(submitted.map((a) => a.question_id))
  }

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3 ring-1 ring-foreground/5 transition-opacity",
        deprioritized && "opacity-60",
      )}
    >
      {/* Header (ex-AccordionTrigger): same info, plus an explicit close button where the
          expand/collapse chevron used to be. */}
      <div className="flex items-center gap-3">
        <ScoreGauge
          value={arm.relevance_score}
          className={cn(rescoring && "animate-pulse")}
        />

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
            {arm.source === "clinician" && (
              <Badge variant="secondary" className="gap-1 font-normal">
                <UserPlus />
                Added by you
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

        <span className="ml-auto flex items-center gap-1.5">
          <ScoreTransitionIndicator transition={transition} />
          <button
            type="button"
            onClick={() => onClose(arm.name)}
            aria-label={`Close ${arm.name}`}
            className="cursor-pointer rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </span>
      </div>

      {/* Body. */}
      <div className="mt-3 space-y-3">
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
          <>
            {/* Unanswered first — full weight, card-level batch submit. */}
            {unanswered.length > 0 && (
              <form onSubmit={handleSubmit} className="space-y-2">
                {unanswered.map((q) => (
                  <QuestionRow
                    key={q.id}
                    question={q}
                    draftValue={drafts[q.id] ?? ""}
                    busy={busy}
                    onDraftChange={onDraftChange}
                  />
                ))}
                <div className="flex items-center justify-end gap-2 pt-0.5">
                  {hasOtherPendingDrafts && (
                    <span className="mr-auto text-xs text-muted-foreground">
                      Submits only this card's answers
                    </span>
                  )}
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
              </form>
            )}

            {/* Answered last — compacted to one line each (no rationale, no input chrome),
                a settled record reusing the same CircleCheck answered marker. */}
            {answered.length > 0 && (
              <div
                className={cn(
                  "space-y-1.5",
                  unanswered.length > 0 && "border-t border-border pt-3",
                )}
              >
                <p className="text-xs font-medium text-muted-foreground">
                  Answered ({answered.length})
                </p>
                {answered.map((q) => (
                  <div key={q.id} className="flex items-start gap-2 text-sm">
                    <CircleCheck
                      className="mt-0.5 size-3.5 shrink-0 text-brand"
                      aria-hidden="true"
                    />
                    <p className="min-w-0">
                      <span className="text-muted-foreground">{q.text}</span>
                      <span className="text-muted-foreground"> — </span>
                      <span className="font-medium text-foreground">{q.answer_text}</span>
                    </p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
