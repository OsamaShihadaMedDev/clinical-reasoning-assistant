/**
 * GlobalRescoreButton — the page-wide "Re-score" control.
 *
 * Submits EVERY pending draft across the whole page (arm cards, suggestion pool, general
 * history) as ONE combined batch → one re-score, instead of one re-score per card. It
 * complements, not replaces, the per-card "Submit answers" buttons (which stay as the fast
 * "just this card" path). It lives inside the docked ComplaintBar next to StreamingStatus,
 * so it's visible regardless of scroll position — the gather-everything action shouldn't
 * be hidden at the bottom of a long page.
 *
 * Hidden entirely when nothing is pending (it earns its place only when there's something
 * to submit), and it reuses the same spinner + disabled in-flight treatment every other
 * submit surface uses, driven by the shared `submittingArm`/`busy` state.
 */

import { LoaderCircle, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"

interface GlobalRescoreButtonProps {
  /** Non-empty drafts across the whole page; the control hides at 0. */
  pendingCount: number
  /** This control's own submit is in flight (submittingArm === GLOBAL_RESCORE_ID). */
  submitting: boolean
  /** Any submit/re-score is in flight — disabled so two re-scores can't overlap. */
  busy: boolean
  onRescore: () => void
}

export function GlobalRescoreButton({
  pendingCount,
  submitting,
  busy,
  onRescore,
}: GlobalRescoreButtonProps) {
  if (pendingCount === 0) return null

  return (
    <Button
      type="button"
      size="sm"
      onClick={onRescore}
      disabled={busy}
      className="cursor-pointer gap-1.5"
    >
      {submitting ? (
        <>
          <LoaderCircle className="animate-spin" />
          Re-scoring…
        </>
      ) : (
        <>
          <RefreshCw />
          Re-score · {pendingCount} pending
        </>
      )}
    </Button>
  )
}
