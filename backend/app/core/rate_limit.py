"""In-memory, per-IP weighted rate limiting for the public demo deployment.

Single-process, single-container deployment (see Dockerfile) — an in-memory store is
correct here the same way `_SESSIONS` in main.py is: there is exactly one process,
so there's no multi-instance consistency problem to solve. If this app is ever
deployed behind multiple replicas, this needs to move to a shared store (Redis) —
flagged here so a future change doesn't silently become wrong under horizontal
scaling.

Each request consumes a number of "units" from a per-IP hourly budget, weighted by
which agent(s) the route triggers — NOT a flat count per request. A route that fires
the Sonnet-tier Prioritization Agent costs more of the budget than one that only
touches Haiku-tier agents, so a re-score-spam script exhausts its budget far faster
than a visitor exploring a few different example complaints does.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request

HOURLY_BUDGET = 80
WINDOW_SECONDS = 3600

# Per-route weight: see module docstring for the cost reasoning behind these numbers.
ROUTE_WEIGHTS: dict[str, int] = {
    "/api/triage": 5,
    "/api/triage/stream": 5,
    "/api/answers": 3,       # triggers Prioritization (Sonnet) + Suggestion (Haiku)
    "/api/arm/custom": 3,    # triggers a Prioritization re-score (Sonnet)
    "/api/arm/expand": 1,    # Question Generator only (Haiku)
    "/api/investigations": 1,  # Investigation Agent only (Haiku)
}
DEFAULT_WEIGHT = 1  # any future route not listed above defaults to the cheap tier

# ip -> list of (timestamp, units) consumed within the current window
_usage: dict[str, list[tuple[float, int]]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For's first hop if present (typical behind Railway/Render/Fly's
    # proxy); fall back to the direct connecting client otherwise. This is "good enough"
    # for abuse-prevention purposes on a portfolio demo, not a security-critical
    # identity system — a spoofed header just means a bad actor blends into "unknown",
    # not that they bypass the limit entirely (the fallback IP still gets limited).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request) -> None:
    """Call at the top of any route that triggers a model call. Raises 429 if the
    calling IP has exhausted its hourly budget; otherwise records this call's cost
    and returns silently."""
    ip = _client_ip(request)
    weight = ROUTE_WEIGHTS.get(request.url.path, DEFAULT_WEIGHT)
    now = time.time()

    # Evict entries outside the current rolling window before checking/consuming.
    window_start = now - WINDOW_SECONDS
    _usage[ip] = [(ts, units) for ts, units in _usage[ip] if ts >= window_start]

    used = sum(units for _, units in _usage[ip])
    if used + weight > HOURLY_BUDGET:
        raise HTTPException(
            status_code=429,
            detail=(
                "Demo rate limit reached for this session. This is a portfolio "
                "demonstration with a shared usage budget — please try again in a "
                "little while."
            ),
        )

    _usage[ip].append((now, weight))
