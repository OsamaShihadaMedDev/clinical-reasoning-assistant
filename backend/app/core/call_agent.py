"""call_agent() — the single abstracted entry point for every OpenRouter call.

CLAUDE.md Section 7 mandates that ALL AI calls go through ONE function rather than
scattering raw HTTP through the codebase. This is that function. It is generic over
the response contract: the caller passes the Pydantic model class it expects back,
and call_agent constrains the model's output to that schema and returns a validated
instance. That genericity is the whole point — the same connector serves the
Triage, Question Generator, and Prioritization agents without per-agent HTTP code,
so prompting/grounding strategy can change later without touching the transport.
"""

import copy
import json
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import OPENROUTER_API_KEY

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# LLM responses routinely take several seconds — past httpx's 5s default, which
# would time out even successful calls. This is the one place the default is
# genuinely inadequate for the workload, so the timeout is widened. Flagged in the
# build report as a deliberate, justified deviation from "httpx defaults only."
_REQUEST_TIMEOUT = httpx.Timeout(60.0)


# Anthropic's structured-output schema validation (the provider behind our routing
# constants) rejects JSON Schema numeric range keywords — it errors with
# "For 'number' type, properties maximum, minimum are not supported". Pydantic emits
# these from Field(ge=..., le=...) constraints (e.g. DiagnosticArm.relevance_score).
# We strip them from the OUTBOUND schema. The bound is NOT lost: Pydantic re-applies
# it when we validate the response below, so an out-of-range value still fails loud —
# it just fails at our validation step instead of at the provider. Defense in depth.
_UNSUPPORTED_SCHEMA_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
)


def _prepare_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Turn a Pydantic-generated JSON schema into one the provider accepts under
    strict structured outputs. Two transformations, applied recursively so nested
    models (TriageOutput -> DiagnosticArm -> ClinicalQuestion, emitted under `$defs`)
    are covered, not just the top-level object:

    1. Strict-mode shape: forbid extra keys on every object (`additionalProperties:
       false`) and list all properties as `required`. Pydantic does neither by
       default. Promoting defaulted fields to required is harmless — the model just
       always emits them and Pydantic still accepts the value coming back in.
    2. Strip the numeric range keywords Anthropic rejects (see
       `_UNSUPPORTED_SCHEMA_KEYS` above for why this is safe).
    """
    schema = copy.deepcopy(schema)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for unsupported in _UNSUPPORTED_SCHEMA_KEYS:
                node.pop(unsupported, None)
            if isinstance(node.get("properties"), dict):
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    return schema


async def call_agent(
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_model: type[BaseModel],
) -> BaseModel:
    """Call OpenRouter with a schema-constrained request and return a validated
    instance of `response_model`.

    `model` is one of the routing constants from config.py, supplied by the caller
    (the agent functions, later) — never hardcoded here, so routing stays config.
    """
    # Defensive guard: the project rule (and this prompt) is to never call out with
    # a missing/placeholder key. Fail loud and specific rather than sending a bad
    # Authorization header and getting an opaque 401 back.
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is empty — set it in backend/.env before calling "
            "call_agent(). Refusing to call OpenRouter without a real key."
        )

    # Pydantic generates the JSON Schema from the contract itself — we never
    # hand-write a schema, so the request shape can never drift from the model.
    # Schema-CONSTRAINED output (the provider forces the reply into this exact
    # shape) has a meaningfully lower malformed-output rate than merely prompting
    # "please return JSON" and parsing the reply. That lower failure rate is why we
    # build this instead of the simpler ask-nicely-and-parse approach.
    schema = _prepare_schema(response_model.model_json_schema())

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": schema,
            },
        },
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    # A fresh AsyncClient per call is fine for this phase — simple and correct. If
    # the orchestration layer later wants connection reuse across the concurrent
    # fan-out, a shared client can be threaded in then; not needed now.
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=payload)

    # Fail loud on a non-200: surface OpenRouter's actual error body so a bad model
    # slug, auth failure, or unsupported-parameter error is immediately visible
    # rather than swallowed.
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter returned HTTP {response.status_code} for model '{model}': "
            f"{response.text}"
        )

    data = response.json()

    # OpenRouter mirrors OpenAI's response shape (choices[0].message.content is a
    # JSON string). If that shape isn't present, show the raw payload instead of
    # raising an opaque KeyError/IndexError.
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Unexpected OpenRouter response shape: {json.dumps(data)[:1000]}"
        ) from exc

    # Validate against the contract. We deliberately do NOT retry on failure: at
    # this phase a malformed/invalid response (bad JSON, a missing field, or an
    # out-of-bounds value like relevance_score=1.7 that slipped past schema
    # enforcement) is a useful debugging signal worth seeing directly, not something
    # to silently paper over. Retry logic is deferred until there's real observed
    # failure-rate data to justify it — building it against a hypothetical failure
    # mode now would be premature.
    try:
        return response_model.model_validate_json(content)
    except Exception as exc:
        raise RuntimeError(
            f"Response failed validation against {response_model.__name__}. "
            f"Raw model content was:\n{content}"
        ) from exc
