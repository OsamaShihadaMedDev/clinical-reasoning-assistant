/**
 * Logo — the Clinical Reasoning Assistant brand mark: a share/network glyph (one source
 * node on the left fanning out to two branch nodes on the right — the "one chief complaint
 * → many diagnostic arms" idea at the heart of the product) set inside a rounded emerald
 * square. Drawn from the same paths and the same design-system tokens as `public/favicon.svg`
 * so the mark is identical in the browser tab and in-app, and follows the theme (uses
 * `bg-primary` / `text-primary-foreground`, so it re-colours correctly in dark mode).
 *
 * `animated` gives the two branch nodes a slow, staggered breathing pulse (keyframes in
 * index.css, auto-disabled under prefers-reduced-motion) so the mark reads as "live"
 * without a glow — used on the landing hero and the docked dashboard corner. Purely
 * decorative: no logic depends on it.
 */
import { cn } from "@/lib/utils"

interface LogoProps {
  /** Sizing (and any extra styling) for the square badge, e.g. "size-5" / "size-7". */
  className?: string
  /** Enable the subtle branch-node pulse. Off by default (renders a static mark). */
  animated?: boolean
}

export function Logo({ className, animated = false }: LogoProps) {
  return (
    <span
      role="img"
      aria-label="Clinical Reasoning Assistant"
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-[30%] bg-primary text-primary-foreground",
        className,
      )}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="size-[62%]"
        aria-hidden="true"
      >
        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
        <circle cx="6" cy="12" r="3" />
        <circle cx="18" cy="5" r="3" className={animated ? "cra-logo-node" : undefined} />
        <circle
          cx="18"
          cy="19"
          r="3"
          className={animated ? "cra-logo-node cra-logo-node--delayed" : undefined}
        />
      </svg>
    </span>
  )
}
