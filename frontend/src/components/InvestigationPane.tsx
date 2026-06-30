/**
 * InvestigationPane — the on-demand "Suggested Workup" right column (Investigation Agent).
 *
 * READ-ONLY by design (v1): suggestions render as a flat list per tier; nothing here is
 * checkable, orderable, or dismissible — there is no per-item state. It is an explicit
 * snapshot the clinician requests via ComplaintBar's "Suggest workup" button, NOT part of
 * the answer/re-score loop and NOT auto-refreshing.
 *
 * Two tiers, each a SIMPLE flat list (Specialized is NOT grouped by arm — each specialized
 * item carries its own arm name as an inline Badge instead): Routine (baseline workup for
 * the complaint, no arm) and Specialized (per top-arm rule-in/rule-out tests). Because the
 * pane does not auto-refresh, it shows a staleness line + manual Refresh whenever more
 * questions have been answered since this batch was generated.
 *
 * App renders this only when `iv.investigations !== null` (the first click), so there is no
 * empty-pane state to handle here — the per-TIER empty states below cover only the rare
 * case the model returns zero items in one tier.
 */

import { FlaskConical, LoaderCircle, RefreshCw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { InvestigationBatch, InvestigationSuggestion } from "@/types"

interface InvestigationPaneProps {
  batch: InvestigationBatch
  /** Answered-question count when `batch` was generated (the staleness baseline). */
  answeredCount: number | null
  /** Current total answered count — compared against `answeredCount` for the staleness line. */
  currentAnsweredCount: number
  /** The Refresh request is in flight (mirrors ComplaintBar's "Suggest workup" loading). */
  loading: boolean
  /** Re-request a fresh snapshot (same handler the ComplaintBar button uses). */
  onRefresh: () => void
  /** Sticky offset so the pane clears the fixed ComplaintBar (App passes barHeight + gap). */
  stickyTop: number
}

/** One workup row: test name (medium weight), one line of reasoning (muted), and — for a
 *  specialized item — its arm name as a secondary Badge (same provenance-badge styling the
 *  suggestion pool uses). No interactive controls: read-only per spec. */
function InvestigationItem({ item }: { item: InvestigationSuggestion }) {
  return (
    <li className="rounded-lg border border-border bg-background px-3 py-2">
      <p className="text-sm font-medium text-foreground">{item.name}</p>
      <p className="mt-0.5 text-xs font-light text-muted-foreground">{item.reasoning}</p>
      {item.arm_name && (
        <Badge variant="secondary" className="mt-1.5 font-normal">
          {item.arm_name}
        </Badge>
      )}
    </li>
  )
}

function Tier({
  title,
  items,
  emptyText,
}: {
  title: string
  items: InvestigationSuggestion[]
  emptyText: string
}) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-xs font-light text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <InvestigationItem key={`${item.name}-${item.arm_name ?? "routine"}`} item={item} />
          ))}
        </ul>
      )}
    </div>
  )
}

export function InvestigationPane({
  batch,
  answeredCount,
  currentAnsweredCount,
  loading,
  onRefresh,
  stickyTop,
}: InvestigationPaneProps) {
  // "M new since": how many questions were answered after this snapshot. Only meaningful
  // when we have a baseline; clamped so a (shouldn't-happen) negative never shows.
  const newSince =
    answeredCount !== null ? Math.max(0, currentAnsweredCount - answeredCount) : 0
  const isStale = newSince > 0

  return (
    <section
      aria-label="Suggested workup"
      className="rounded-xl border border-border bg-card p-4 lg:sticky"
      style={{ top: stickyTop }}
    >
      <h2 className="flex items-center gap-2 font-heading text-sm font-semibold text-foreground">
        <FlaskConical className="size-4 text-brand" />
        Suggested Workup
      </h2>
      <p className="mt-0.5 text-xs font-light text-muted-foreground">
        Tests to consider — not orders. The clinician decides.
      </p>

      {isStale && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5">
          <span className="text-xs text-muted-foreground">
            Generated after {answeredCount}{" "}
            {answeredCount === 1 ? "answer" : "answers"} — {newSince} new since
          </span>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium text-brand transition-colors hover:bg-accent disabled:opacity-60"
          >
            {loading ? (
              <LoaderCircle className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            Refresh
          </button>
        </div>
      )}

      <div className="mt-3 space-y-4">
        <Tier
          title="Routine"
          items={batch.routine}
          emptyText="No additional routine workup suggested"
        />
        <Tier
          title="Specialized"
          items={batch.specialized}
          emptyText="No specialized workup suggested for the current differential"
        />
      </div>
    </section>
  )
}
