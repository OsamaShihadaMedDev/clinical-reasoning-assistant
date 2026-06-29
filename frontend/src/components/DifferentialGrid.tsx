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

import { useMemo, useState } from "react"
import {
  Activity,
  ChevronRight,
  LoaderCircle,
  Plus,
  Sparkles,
  TriangleAlert,
  UserPlus,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
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
  /** Active arms whose score is being recalculated right now — pulses their gauge. */
  rescoringArmNames: Set<string>
  /** Most recent suggestion batch — feeds the Tier 2 "just suggested" condition. */
  suggestions: SuggestionBatch | null
  leaderName: string | null
  onOpen: (armName: string) => void
  /** Add one or more clinician-named diagnoses (scored together). Resolves true on a
   *  successful re-score, false if the server rejected the names (the docked status chip
   *  shows the reason). */
  onAddCustomArms: (names: string[]) => Promise<boolean>
  /** The add control's own submit is in flight. */
  adding: boolean
  /** Any submit/re-score is in flight (disables the add form). */
  busy: boolean
}

interface ArmTileProps {
  arm: DiagnosticArm
  isLeader: boolean
  transition: ScoreTransition | undefined
  /** Tier 2 attention fired for this (closed, red-flag) arm — escalated treatment. */
  needsAttention: boolean
  /** This arm's score is mid-recalculation — pulse the gauge (the identity/name/current
   *  score is still valid, only the score is about to change). */
  rescoring: boolean
  onOpen: (armName: string) => void
}

function ArmTile({
  arm,
  isLeader,
  transition,
  needsAttention,
  rescoring,
  onOpen,
}: ArmTileProps) {
  const flagged = isRedFlagged(arm.reasoning)
  const deprioritized = arm.status === "deprioritized"
  const clinician = arm.source === "clinician"
  return (
    <button
      type="button"
      onClick={() => onOpen(arm.name)}
      className={cn(
        // Vertical-rectangle tile (taller than wide in a multi-column cell): the content
        // stacks top-to-bottom and the tile fills its grid cell width. `group` +
        // `cursor-pointer` + the hover lift signal it's tappable (matching the suggestion
        // cards' interactive language).
        "group relative flex h-full w-full cursor-pointer flex-col items-center gap-1.5 overflow-hidden rounded-xl border bg-card px-3 py-4 text-center transition-transform duration-200 ease-out hover:-translate-y-0.5",
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

      {/* Expand affordance: a muted chevron bottom-right that nudges on hover, so the tile
          visibly reads as "tap to open the full card". */}
      <ChevronRight
        className="absolute bottom-2 right-2 size-3.5 text-muted-foreground transition-transform duration-200 ease-out group-hover:translate-x-0.5"
        aria-hidden="true"
      />

      <ScoreGauge
        value={arm.relevance_score}
        size={52}
        strokeWidth={5}
        className={cn(rescoring && "animate-pulse")}
      />

      <span className="line-clamp-2 font-heading text-sm font-medium leading-tight text-foreground">
        {arm.name}
      </span>

      {/* Provenance: clinician-added arms are marked everywhere their name renders. */}
      {clinician && (
        <span className="inline-flex items-center gap-1 text-[0.6rem] font-medium text-muted-foreground">
          <UserPlus className="size-2.5" />
          Added by you
        </span>
      )}

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
  rescoringArmNames,
  suggestions,
  leaderName,
  onOpen,
  onAddCustomArms,
  adding,
  busy,
}: DifferentialGridProps) {
  // The "Add a custom diagnosis" inline form: open/closed, the raw textarea text (one
  // diagnosis per line — chosen over a repeating-input row for least chrome and easy
  // multi-add), and a client-side validation message. Server-side rejections (empty /
  // duplicate) surface in the docked status chip, so they aren't duplicated here.
  const [addOpen, setAddOpen] = useState(false)
  const [addDraft, setAddDraft] = useState("")
  const [localError, setLocalError] = useState<string | null>(null)

  async function handleAddSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    const names = addDraft
      .split("\n")
      .map((n) => n.trim())
      .filter((n) => n.length > 0)
    if (names.length === 0) {
      setLocalError("Enter at least one diagnosis (one per line).")
      return
    }
    setLocalError(null)
    const ok = await onAddCustomArms(names)
    // On success clear + close; on a server rejection keep the form open so the clinician
    // can fix the name (the reason shows in the docked status chip).
    if (ok) {
      setAddDraft("")
      setAddOpen(false)
    }
  }

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-sm font-semibold text-foreground">
          Differential ({arms.length})
        </h2>
        <div className="flex items-center gap-2">
          {/* Non-positional mobile cue (useful on desktop too): a persistent count of arms
              needing a look, in the same --flag colour, only when > 0. On a single-column
              scroll the coloured tiles can be off-screen; this summary never is. */}
          {attentionCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-flag/10 px-2 py-0.5 text-xs font-semibold text-flag">
              <TriangleAlert className="size-3" />
              {attentionCount} need{attentionCount === 1 ? "s" : ""} attention
            </span>
          )}
          {/* Clinician-added differentials: suspected something the system missed. */}
          <button
            type="button"
            onClick={() => setAddOpen((o) => !o)}
            aria-expanded={addOpen}
            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-brand transition-colors hover:bg-accent"
          >
            <Plus className="size-3.5" />
            Add diagnosis
          </button>
        </div>
      </div>

      {/* Inline add form: one diagnosis per line; multiple are added — and scored —
          TOGETHER in one re-score. */}
      {addOpen && (
        <form
          onSubmit={handleAddSubmit}
          className="space-y-2 rounded-xl border border-border bg-card p-3"
        >
          <label
            htmlFor="custom-diagnosis"
            className="text-xs font-medium text-foreground"
          >
            Add custom diagnoses — one per line
          </label>
          <Textarea
            id="custom-diagnosis"
            value={addDraft}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
              setAddDraft(e.target.value)
              if (localError) setLocalError(null)
            }}
            placeholder={"e.g.\nBoerhaave syndrome\nMyopericarditis"}
            rows={3}
            disabled={busy}
            aria-label="Custom diagnoses, one per line"
            className="resize-none text-sm"
          />
          <div className="flex items-center justify-end gap-2">
            {localError && (
              <span className="mr-auto text-xs text-flag">{localError}</span>
            )}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setAddOpen(false)}
              className="cursor-pointer"
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={busy || addDraft.trim().length === 0}
              className="cursor-pointer"
            >
              {adding ? (
                <>
                  <LoaderCircle className="animate-spin" />
                  Adding…
                </>
              ) : (
                <>
                  <Plus />
                  Add &amp; re-score
                </>
              )}
            </Button>
          </div>
        </form>
      )}

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
              rescoring={rescoringArmNames.has(arm.name)}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </section>
  )
}
