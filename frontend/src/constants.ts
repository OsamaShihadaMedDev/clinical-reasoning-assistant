/**
 * Frontend-side tunable constants (the client-side counterpart to backend/app/config.py).
 * Named, documented knobs rather than magic numbers buried in JSX.
 */

// Minimum |score delta| for an arm to appear in the post-rescore summary. Below this,
// movement is treated as noise-floor jitter rather than a clinically meaningful shift —
// same reasoning as backend/app/config.py's TOP_N_INVESTIGATION_ARMS: a named, tunable
// constant rather than a magic number buried in JSX. Deliberately a THRESHOLD, not a
// fixed top-N: a quiet rescore should show few/zero arms, not be padded to a fixed
// count, and a dramatic rescore should be able to show many — the count itself is
// signal (see backend's SUGGESTION_POOL_SIZE comment: "must not pad to hit this
// number" — same principle applies here).
export const RESCORE_SUMMARY_THRESHOLD = 0.05
