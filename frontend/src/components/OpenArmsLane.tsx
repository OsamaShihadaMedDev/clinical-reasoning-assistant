/**
 * OpenArmsLane — the Open Cards Lane: up to MAX_OPEN_ARMS full DiagnosticArmCards the
 * clinician is actively working, stacked full-width.
 *
 * Order is `openArms` order (oldest-opened first), NOT score order — a card's position
 * reflects WHEN it was opened, not its current likelihood, so a re-score never reshuffles
 * the cards under the clinician's hands. Renders nothing when the lane is empty.
 *
 * Pulse: when App targets an arm that is ALREADY open (e.g. a suggestion's "Expand full
 * card" for an arm in the lane), opening is a no-op, so the tap would otherwise feel
 * silent. App bumps a `pulse` signal for that arm; the matching LaneCard scrolls itself
 * into view and briefly flashes a ring (reusing the standard ~200ms ease-out transform/
 * colour convention). A freshly-opened card pulses on mount too, so the same path nicely
 * scrolls new opens into view.
 */

import { useEffect, useRef } from "react"

import { DiagnosticArmCard } from "@/components/DiagnosticArmCard"
import type { DiagnosticArm, ScoreTransition } from "@/types"

/** The transient pulse-flash ring (Tailwind utilities, kept as string literals here so
 *  the v4 scanner still emits them). Added/removed directly on the node in the effect —
 *  a DOM-only side effect, not React state, so it doesn't trigger cascading renders. */
const FLASH_CLASSES = ["ring-2", "ring-primary", "ring-offset-2", "ring-offset-background"]

interface OpenArmsLaneProps {
  openArms: string[]
  arms: DiagnosticArm[]
  leaderName: string | null
  recentTransitions: Record<string, ScoreTransition>
  generating: boolean
  expandingArms: Set<string>
  submittingArm: string | null
  busy: boolean
  onAnswerBatch: (
    cardId: string,
    answers: { question_id: string; answer_text: string }[],
  ) => Promise<boolean>
  onClose: (armName: string) => void
  /** A monotonically-increasing signal + the targeted arm name. When `signal` changes for
   *  a card whose name === `name`, that card scrolls into view and flashes. */
  pulse: { name: string | null; signal: number }
}

/** One lane slot: owns its scroll target ref and a transient flash on pulse. The
 *  `pulseSignal` it receives is non-zero ONLY when this card is the pulse target, so its
 *  effect fires for the targeted card alone. */
function LaneCard({
  pulseSignal,
  children,
}: {
  pulseSignal: number
  children: React.ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (pulseSignal === 0) return // not the pulse target (or no pulse yet) — do nothing
    const node = ref.current
    if (!node) return
    node.scrollIntoView({ behavior: "smooth", block: "center" })
    // DOM-only flash: add the ring now, remove it after the hold. No React state, so this
    // synchronises with the DOM (the rule's blessed use of an effect) without cascading
    // renders — and there's nothing to re-render anyway, only a class toggle.
    node.classList.add(...FLASH_CLASSES)
    const t = setTimeout(() => node.classList.remove(...FLASH_CLASSES), 600)
    return () => clearTimeout(t)
  }, [pulseSignal])

  return (
    <div ref={ref} className="rounded-xl transition-shadow duration-200 ease-out">
      {children}
    </div>
  )
}

export function OpenArmsLane({
  openArms,
  arms,
  leaderName,
  recentTransitions,
  generating,
  expandingArms,
  submittingArm,
  busy,
  onAnswerBatch,
  onClose,
  pulse,
}: OpenArmsLaneProps) {
  if (openArms.length === 0) return null

  const byName = new Map(arms.map((a) => [a.name, a]))

  return (
    <section aria-label="Open arm cards" className="space-y-3">
      {openArms.map((name) => {
        const arm = byName.get(name)
        if (!arm) return null // arm vanished from triage (shouldn't happen) — skip safely
        return (
          <LaneCard key={name} pulseSignal={pulse.name === name ? pulse.signal : 0}>
            <DiagnosticArmCard
              arm={arm}
              isLeader={arm.name === leaderName}
              transition={recentTransitions[arm.name]}
              generating={generating}
              expanding={expandingArms.has(arm.name)}
              submitting={submittingArm === arm.name}
              busy={busy}
              onAnswerBatch={onAnswerBatch}
              onClose={onClose}
            />
          </LaneCard>
        )
      })}
    </section>
  )
}
