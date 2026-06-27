/**
 * Shared clinical UI helpers.
 *
 * The Prioritization Agent flags a can't-miss arm in its REASONING TEXT (an honest
 * "cannot be excluded…" note) rather than by inflating the score (CLAUDE.md Section 7).
 * This detects that tell. Extracted here so the differential strip, suggestion pool, and
 * arm cards all read "red-flag" the same way instead of duplicating the regex.
 *
 * NOTE: this is the per-ARM, reasoning-derived signal. The Suggestion Agent separately
 * sends an authoritative `is_red_flag` boolean on each SuggestedQuestion (computed
 * server-side from the framework's red-flag arms) — prefer that field where available;
 * use this helper for arms, which carry only reasoning text on the client.
 */
export function isRedFlagged(reasoning: string): boolean {
  return /cannot be excluded|red flag|can't-miss|cant-miss/i.test(reasoning)
}
