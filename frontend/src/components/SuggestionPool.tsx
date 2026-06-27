/**
 * SuggestionPool — the clinician-led "what to ask next" surface (Suggestion Agent).
 *
 * Renders the backend's already-RANKED list (do not re-sort) as tappable cards: top
 * `POOL_FOLD` shown, the rest behind "Show N more". Each card is a question pulled from
 * ACROSS all active arms (not grouped by arm), so the clinician picks freely rather than
 * working through arm cards top-to-bottom. Tapping a card reveals an inline answer input;
 * submitting goes through the SAME `answerBatch` flow the arm cards use (the backend
 * routes by id), and the pool re-ranks on the next `done`.
 *
 * No free-text question entry by product decision — the pool only ever surfaces
 * agent-suggested questions that already exist in the system.
 */

import { useState } from "react"
import { Check, History, LoaderCircle, Sparkles, TriangleAlert } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { SUGGESTION_CARD_ID } from "@/hooks/useInterview"
import { cn } from "@/lib/utils"
import type { SuggestedQuestion, SuggestionBatch } from "@/types"

/** How many to show before the fold. The backend caps at SUGGESTION_POOL_SIZE (4) today,
 *  so "show more" is a no-op now but renders correctly if the list ever exceeds this. */
const POOL_FOLD = 4

interface SuggestionPoolProps {
  suggestions: SuggestionBatch | null
  /** True while any submit/re-score is in flight (disables inputs). */
  busy: boolean
  /** This pool's submit is in flight (drives the active card's button loading). */
  submitting: boolean
  onAnswerBatch: (
    cardId: string,
    answers: { question_id: string; answer_text: string }[],
  ) => Promise<boolean>
}

export function SuggestionPool({
  suggestions,
  busy,
  submitting,
  onAnswerBatch,
}: SuggestionPoolProps) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [showAll, setShowAll] = useState(false)

  const Header = (
    <h2 className="mb-2 flex items-center gap-2 font-heading text-sm font-semibold text-foreground">
      <Sparkles className="size-4 text-brand" />
      Suggested next questions
    </h2>
  )

  // Loading: suggestions not yet ranked (initial stream). Skeletons sized to the cards.
  if (suggestions === null) {
    return (
      <section aria-label="Suggested next questions">
        {Header}
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="rounded-xl border border-border bg-card px-4 py-3">
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="mt-1.5 h-3 w-3/5" />
            </div>
          ))}
        </div>
      </section>
    )
  }

  const all = suggestions.suggestions
  if (all.length === 0) {
    return (
      <section aria-label="Suggested next questions">
        {Header}
        <p className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          No suggested questions right now — the most useful questions have been asked.
        </p>
      </section>
    )
  }

  const visible = showAll ? all : all.slice(0, POOL_FOLD)
  const hiddenCount = all.length - visible.length

  async function handleSubmit(s: SuggestedQuestion) {
    const text = draft.trim()
    if (!text || busy) return
    const ok = await onAnswerBatch(SUGGESTION_CARD_ID, [
      { question_id: s.question_id, answer_text: text },
    ])
    if (ok) {
      setOpenId(null)
      setDraft("")
    }
  }

  return (
    <section aria-label="Suggested next questions">
      {Header}
      <div className="space-y-2">
        {visible.map((s) => {
          const open = openId === s.question_id
          return (
            <div
              key={s.question_id}
              className={cn(
                "relative overflow-hidden rounded-xl border bg-card transition-transform duration-200 ease-out",
                s.is_red_flag ? "border-flag/40" : "border-border",
              )}
            >
              {s.is_red_flag && (
                <span className="absolute inset-y-0 left-0 w-1 bg-flag" aria-hidden="true" />
              )}

              <button
                type="button"
                onClick={() => {
                  setOpenId(open ? null : s.question_id)
                  setDraft("")
                }}
                aria-expanded={open}
                className="block w-full px-4 py-3 text-left"
              >
                <p className="text-sm font-medium text-foreground">{s.question_text}</p>
                {/* Justification: deliberately lighter/shorter than arm.reasoning. */}
                <p className="mt-0.5 text-xs font-light text-muted-foreground">
                  {s.justification}
                </p>

                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  {s.is_red_flag && (
                    <Badge variant="destructive" className="gap-1">
                      <TriangleAlert className="size-3" />
                      Red flag
                    </Badge>
                  )}
                  {s.is_history_question && (
                    <Badge variant="secondary" className="gap-1 font-normal">
                      <History className="size-3" />
                      General history
                    </Badge>
                  )}
                  {s.source_arms.map((arm) => (
                    <Badge key={arm} variant="secondary" className="font-normal">
                      {arm}
                    </Badge>
                  ))}
                </div>
              </button>

              {open && (
                <form
                  className="flex items-center gap-2 px-4 pb-3"
                  onSubmit={(e) => {
                    e.preventDefault()
                    void handleSubmit(s)
                  }}
                >
                  <Input
                    autoFocus
                    value={draft}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      setDraft(e.target.value)
                    }
                    placeholder="Type the patient's answer…"
                    disabled={busy}
                    aria-label={`Answer for: ${s.question_text}`}
                    className="h-8"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={draft.trim().length === 0 || busy}
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
                        Submit
                      </>
                    )}
                  </Button>
                </form>
              )}
            </div>
          )
        })}
      </div>

      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-xs font-medium text-brand"
        >
          {showAll ? "Show fewer" : `Show ${hiddenCount} more`}
        </button>
      )}
    </section>
  )
}
