/**
 * DifferentialGrid — the Closed Grid of diagnostic arms (formerly DifferentialStrip).
 *
 * Its job changed from "the only arm view" to specifically "the CLOSED-cards grid": it
 * renders every active arm that is NOT currently open in the Open Cards Lane, as compact
 * vertical-rectangle tiles. Tapping a tile opens that arm's full card in the lane
 * (`onOpen`, not the old single-select `onSelect`). Open arms move into the lane and are
 * filtered out here so an arm never renders in both places at once.
 *
 * Two tiers of signal live on these tiles (Part B):
 *  - Tier 1 (ambient): the score gauge + the transient old->new ScoreTransitionIndicator,
 *    exactly as before. Non-red-flag arms only ever get Tier 1, no matter how much they
 *    move — a loud signal that fires constantly stops being useful.
 *  - Tier 2 (attention): a red-flag arm that ALSO just moved or was just suggested gets an
 *    ESCALATED version of the existing `--flag` language (a pulsing dot + a filled flag
 *    badge, on top of the subtle left accent bar a routine red-flag arm already shows),
 *    so "newly needs a look" is distinguishable from "routinely a can't-miss". Opening the
 *    arm clears it (the tile leaves the grid), so the indicator is derived per-render with
 *    no acknowledgement state to keep in sync.
 *
 * General History is NOT rendered here: per the chosen approach (option b — least prop-
 * drilling), App.tsx keeps rendering the full interactive HistoryCard as a separate
 * adjacent element pinned ABOVE this grid, styled to match. It has no ScoreGauge and a
 * checklist icon already, so it reads as the visually-distinct, score-sort-excluded
 * "pinned first" card the design calls for without threading its 5 props through here.
 *
 * Mobile: single column, stacked (no collapse-to-leader — the vertical-rectangle tile is
 * already narrow enough at single-column width). Multi-column at sm+.
 */

import { useMemo } from "react"
import { Activity, Sparkles, TriangleAlert } from "lucide-react"

import { ScoreGauge } from "@/components/ScoreGauge"
import { ScoreTransitionIndicator } from "@/components/ScoreTransitionIndicator"
import { isRedFlagged } from "@/lib/clinical"
import { cn } from "@/lib/utils"
import type {
  DiagnosticArm,
  ScoreTransition,
  SuggestionBatch,
} from "@/types"

interface DifferentialGridProps {
  arms: DiagnosticArm[]
  /** Names currently open in the lane — excluded from this grid. */
  openArms: string[]
  recentTransitions: Record<string, ScoreTransition>
  /** Most recent suggestion batch — feeds the Tier 2 "just suggested" condition. */
  suggestions: SuggestionBatch | null
  leaderName: string | null
  onOpen: (armName: string) => void
}

interface ArmTileProps {
  arm: DiagnosticArm
  isLeader: boolean
  transition: ScoreTransition | undefined
  /** Tier 2 attention fired for this (closed, red-flag) arm — escalated treatment. */
  needsAttention: boolean
  onOpen: (armName: string) => void
}

function ArmTile({ arm, isLeader, transition, needsAttention, onOpen }: ArmTileProps) {
  const flagged = isRedFlagged(arm.reasoning)
  const deprioritized = arm.status === "deprioritized"
  return (
    <button
      type="button"
      onClick={() => onOpen(arm.name)}
      className={cn(
        // Vertical-rectangle tile (taller than wide in a multi-column cell): the content
        // stacks top-to-bottom and the tile fills its grid cell width.
        "relative flex h-full w-full flex-col items-center gap-1.5 overflow-hidden rounded-xl border bg-card px-3 py-4 text-center transition-transform duration-200 ease-out hover:-translate-y-0.5",
        flagged ? "border-flag/40" : "border-border",
        // Tier 2: escalate the same --flag language with a ring (stronger than the subtle
        // left bar alone) so it reads louder than a routine red-flag tile.
        needsAttention && "ring-2 ring-flag/60",
        deprioritized && "opacity-60",
      )}
    >
      {/* Routine red-flag lane: the subtle left accent bar (paired with the label below). */}
      {flagged && (
        <span className="absolute inset-y-0 left-0 w-1 bg-flag" aria-hidden="true" />
      )}

      {/* Tier 2 escalation: a pulsing filled dot top-right — motion, not colour alone. */}
      {needsAttention && (
        <span
          className="absolute right-2 top-2 size-2.5 animate-pulse rounded-full bg-flag"
          aria-hidden="true"
        />
      )}

      <ScoreGauge value={arm.relevance_score} size={52} strokeWidth={5} />

      <span className="line-clamp-2 font-heading text-sm font-medium leading-tight text-foreground">
        {arm.name}
      </span>

      {needsAttention ? (
        // Escalated filled badge — louder than the routine outline "Red flag" label.
        <span className="inline-flex items-center gap-1 rounded-full bg-flag px-2 py-0.5 text-[0.65rem] font-semibold text-white">
          <TriangleAlert className="size-3" />
          Needs review
        </span>
      ) : isLeader ? (
        <span className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-brand">
          <Sparkles className="size-3" />
          Leading
        </span>
      ) : flagged ? (
        <span className="inline-flex items-center gap-1 text-[0.65rem] font-medium text-flag">
          <TriangleAlert className="size-3" />
          Red flag
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 text-[0.65rem] text-muted-foreground">
          <Activity className="size-3 text-brand-secondary" />
          Active
        </span>
      )}

      <ScoreTransitionIndicator transition={transition} />
    </button>
  )
}

export function DifferentialGrid({
  arms,
  openArms,
  recentTransitions,
  suggestions,
  leaderName,
  onOpen,
}: DifferentialGridProps) {
  // Arms a suggestion in the most-recent batch points at (by name) — the Tier 2
  // "just suggested" trigger. Memoised so it isn't rebuilt on every unrelated render.
  const suggestedArmNames = useMemo(() => {
    const set = new Set<string>()
    for (const s of suggestions?.suggestions ?? []) {
      for (const name of s.source_arms) set.add(name)
    }
    return set
  }, [suggestions])

  if (arms.length === 0) return null

  const open = new Set(openArms)
  const closedArms = arms.filter((a) => !open.has(a.name))

  // Tier 2 fires only for red-flag arms that ALSO just moved or were just suggested. All
  // tiles here are closed by construction (open arms are filtered out), so the design's
  // "and currently closed" clause is satisfied implicitly — opening one removes it.
  const needsAttention = (arm: DiagnosticArm) =>
    isRedFlagged(arm.reasoning) &&
    (recentTransitions[arm.name] !== undefined || suggestedArmNames.has(arm.name))

  const attentionCount = closedArms.filter(needsAttention).length

  return (
    <section aria-label="Differential" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-heading text-sm font-semibold text-foreground">
          Differential ({arms.length})
        </h2>
        {/* Non-positional mobile cue (useful on desktop too): a persistent count of arms
            needing a look, in the same --flag colour, only when > 0. On a single-column
            scroll the coloured tiles can be off-screen; this summary never is. */}
        {attentionCount > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-flag/10 px-2 py-0.5 text-xs font-semibold text-flag">
            <TriangleAlert className="size-3" />
            {attentionCount} need{attentionCount === 1 ? "s" : ""} attention
          </span>
        )}
      </div>

      {closedArms.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
          Every arm is open above.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
          {closedArms.map((arm) => (
            <ArmTile
              key={arm.name}
              arm={arm}
              isLeader={arm.name === leaderName}
              transition={recentTransitions[arm.name]}
              needsAttention={needsAttention(arm)}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </section>
  )
}
