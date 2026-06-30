"""Translates internal exceptions into short, non-leaking messages safe to show a
public demo visitor. The raw exception is still logged server-side in full (via
Python's standard logging, NOT swallowed) — this module only controls what reaches
the client's `detail` field over SSE/JSON. Internal architecture (model slugs,
provider response bodies, stack traces) must never reach the browser on a public,
unauthenticated demo.
"""

import logging

from fastapi import HTTPException

logger = logging.getLogger("clinical_reasoning_assistant")


def public_error_detail(exc: Exception) -> str:
    """Map an exception to a short, friendly client-facing message. Logs the full
    original exception server-side regardless of which branch matches, so nothing
    is lost for debugging — only what the CLIENT sees is shortened."""
    logger.exception("Request failed", exc_info=exc)

    message = str(exc)

    if isinstance(exc, HTTPException) and exc.status_code == 429:
        # Our own rate limiter's HTTPException already carries a friendly detail
        # (see core/rate_limit.py) — pass it through as-is rather than re-wrapping.
        return str(exc.detail)

    if "OpenRouter returned HTTP 429" in message:
        return (
            "The demo is experiencing high demand right now. Please wait a moment "
            "and try again."
        )
    if "OpenRouter returned HTTP" in message or "Unexpected OpenRouter response" in message:
        return (
            "Something went wrong generating a response. Please try again — if it "
            "keeps happening, the underlying AI service may be temporarily "
            "unavailable."
        )
    if "validation against" in message:
        return (
            "The AI response didn't come back in the expected format. Please try "
            "again."
        )
    if "OPENROUTER_API_KEY is empty" in message:
        # This one is a deploy misconfiguration, not a transient failure — still
        # don't leak the env var name to a visitor, but this case is worth being
        # distinguishable in server logs (already is, via logger.exception above).
        return "The demo isn't fully configured right now. Please check back later."

    # Fallback for anything unanticipated: still friendly, still no internals leaked.
    return "Something unexpected went wrong. Please try again."
