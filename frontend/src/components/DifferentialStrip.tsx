/**
 * DifferentialStrip — the primary at-a-glance view of the differential, replacing the
 * old full-width arms Accordion. A horizontally-scrollable row of compact cards, one
 * per active arm (same sort order useInterview.arms provides), each showing the arm
 * name, a small ScoreGauge, and the transient old→new delta when it just re-scored.
 *
 * Red-flag (can't-miss) arms get a distinct visual LANE — a left `--flag` accent bar
 * plus an icon+label (never colour-only) — so they stand out from likelihood ranking.
 * Tapping a card expands that arm's full question list below the strip (handled by the
 * parent via `onSelect`; the expanded detail reuses DiagnosticArmCard).
 *
 * Mobile: condensed by default to a single summary card (the leader) with a chevron to
 * reveal the full strip; on `sm+` the full strip always shows.
 */

import { useState } from "react"
import {
  Activity,
  ChevronDown,
  ChevronUp,
  Sparkles,
  TriangleAlert,
} from "lucide-react"

import { ScoreGauge } from "@/components/ScoreGauge"
import { ScoreTransitionIndicator } from "@/components/ScoreTransitionIndicator"
import { isRedFlagged } from "@/lib/clinical"
import { cn } from "@/lib/utils"
import type { DiagnosticArm, ScoreTransition } from "@/types"

interface DifferentialStripProps {
  arms: DiagnosticArm[]
  recentTransitions: Record<string, ScoreTransition>
  leaderName: string | null
  selectedArm: string | null
  onSelect: (armName: string) => void
}

interface ArmCardProps {
  arm: DiagnosticArm
  isLeader: boolean
  isSelected: boolean
  transition: ScoreTransition | undefined
  onSelect: (armName: string) => void
}

function ArmCard({ arm, isLeader, isSelected, transition, onSelect }: ArmCardProps) {
  const flagged = isRedFlagged(arm.reasoning)
  const deprioritized = arm.status === "deprioritized"
  return (
    <button
      type="button"
      onClick={() => onSelect(arm.name)}
      aria-pressed={isSelected}
      className={cn(
        "relative flex w-40 shrink-0 snap-start flex-col items-center gap-1.5 overflow-hidden rounded-xl border bg-card px-3 py-3 text-center transition-transform duration-200 ease-out hover:-translate-y-0.5",
        flagged ? "border-flag/40" : "border-border",
        isSelected && "ring-2 ring-primary",
        deprioritized && "opacity-60",
      )}
    >
      {/* Distinct red-flag lane: left accent bar (paired with the icon+label below). */}
      {flagged && (
        <span className="absolute inset-y-0 left-0 w-1 bg-flag" aria-hidden="true" />
      )}

      <ScoreGauge value={arm.relevance_score} size={48} strokeWidth={5} />

      <span className="line-clamp-2 font-heading text-xs font-medium leading-tight text-foreground">
        {arm.name}
      </span>

      {isLeader ? (
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

export function DifferentialStrip({
  arms,
  recentTransitions,
  leaderName,
  selectedArm,
  onSelect,
}: DifferentialStripProps) {
  // Mobile-only collapse (condensed to the leader). On sm+ the full strip always shows
  // (the cards container forces `sm:flex`), so this only affects narrow screens.
  const [collapsed, setCollapsed] = useState(true)

  if (arms.length === 0) return null
  const leader = arms.find((a) => a.name === leaderName) ?? arms[0]

  return (
    <section aria-label="Differential" className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-sm font-semibold text-foreground">
          Differential ({arms.length})
        </h2>
        {/* Mobile-only expand/collapse toggle. */}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground sm:hidden"
        >
          {collapsed ? (
            <>
              Show all <ChevronDown className="size-3.5" />
            </>
          ) : (
            <>
              Collapse <ChevronUp className="size-3.5" />
            </>
          )}
        </button>
      </div>

      {/* Full strip: horizontal scroll. Hidden on mobile when collapsed; always shown sm+. */}
      <div
        className={cn(
          "snap-x gap-2 overflow-x-auto pb-1 [scrollbar-width:thin]",
          collapsed ? "hidden sm:flex" : "flex",
        )}
      >
        {arms.map((arm) => (
          <ArmCard
            key={arm.name}
            arm={arm}
            isLeader={arm.name === leaderName}
            isSelected={arm.name === selectedArm}
            transition={recentTransitions[arm.name]}
            onSelect={onSelect}
          />
        ))}
      </div>

      {/* Mobile condensed summary: just the leader, shown only when collapsed. */}
      {collapsed && (
        <div className="sm:hidden">
          <ArmCard
            arm={leader}
            isLeader={leader.name === leaderName}
            isSelected={leader.name === selectedArm}
            transition={recentTransitions[leader.name]}
            onSelect={onSelect}
          />
        </div>
      )}
    </section>
  )
}
