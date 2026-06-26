/**
 * ScoreGauge — a circular 0–1 relevance ring, adapted from the Sustainable Energy
 * demo's score ring. The arc length is driven by stroke-dashoffset and CSS-animated,
 * so when an arm re-scores the ring visibly sweeps from the old value to the new one
 * (transform/opacity-class motion only — no width/height animation).
 */

import { useId } from "react"

import { cn } from "@/lib/utils"

interface ScoreGaugeProps {
  /** Relevance score in [0, 1]. */
  value: number
  size?: number
  strokeWidth?: number
  className?: string
}

export function ScoreGauge({
  value,
  size = 60,
  strokeWidth = 6,
  className,
}: ScoreGaugeProps) {
  const gradientId = useId()
  const pct = Math.max(0, Math.min(1, value))
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - pct)
  const percent = Math.round(pct * 100)

  return (
    <div
      className={cn("relative shrink-0", className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Relevance score ${percent} percent`}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--brand-secondary)" />
            <stop offset="100%" stopColor="var(--brand)" />
          </linearGradient>
        </defs>
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--muted)"
          strokeWidth={strokeWidth}
        />
        {/* Value arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: "stroke-dashoffset 600ms ease-out",
          }}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-heading text-sm font-semibold tabular-nums text-foreground">
        {percent}
        <span className="text-[0.6rem] font-normal text-muted-foreground">%</span>
      </span>
    </div>
  )
}
