# CLAUDE.md — Clinical Reasoning Assistant

> Persistent context for every Claude Code session on this project. Read this before making any architectural decision. If a suggestion (from an audit, from me, from anywhere) conflicts with something locked in here, flag the conflict explicitly rather than silently deviating.

---

## 0. Positioning — read this before anything else

This is a **stateful multi-agent orchestration system, built in Python, using medicine as the domain** — not "a medical app with AI in it." That distinction shapes every description of this project: README, resume bullet, GitHub description, code comments, how it gets talked about in interviews.

The medical domain is the proof of depth (it's hard, it's mine, it's credible coming from a near-qualified physician) — but the headline skill being demonstrated is agent orchestration, state management, and systems design. Do not let the implementation or its description drift into "a history-taking app" — that undersells it.

---

## 1. Who is building this

Final-year MBBS student at Al-Azhar University Gaza, solo founder/developer of StudyBuddy AI (studybuddyai.com) — a live AI-powered medical education platform with a working QBank, AI sheet generator, and paying users. Existing stack: React, TypeScript, Vite, Tailwind, shadcn/ui, Supabase, Vercel, OpenRouter, Express, Claude Code with Playwright MCP.

Completed a focused one-week Python fundamentals course (environment setup, API handling, `.env` patterns, `uv`, VS Code navigation) — can read Python well and understands core concepts but is not yet fluent writing it from scratch. **This project is built primarily through Claude Code, with Osama directing architecture, reviewing logic, and understanding every decision — not blindly accepting generated code.**

**Working style: explain the "why," not just deliver working code.** This matters most for Pydantic contracts and agent orchestration logic — that's what Osama is leaning on Claude Code hardest for, and what he most needs to actually understand afterward.

---

## 2. The problem this solves

A patient presents with a chief complaint; a systematic, targeted set of history-taking questions is needed to build toward a diagnosis — but generic textbook templates (SOCRATES, systems review) don't adapt to the specific patient or complaint in front of the clinician. This is a real problem Osama would use during clinical rotations, not an invented portfolio premise.

Existing tools fail because they're either rigid static checklists or too generic. Nothing reasons in terms of **diagnostic arms** the way a clinician actually does.

---

## 3. The core idea — diagnostic arms, not flat checklists

When a complaint comes in, branch it into **diagnostic arms** (pathophysiological categories), and generate targeted questions under each arm, weighted by relevance to the specific patient.

**Example: chest pain, 60yo male smoker**
- Cardiac arm → ischemic vs non-ischemic questions
- Vascular arm → dissection, PE risk factors
- Respiratory arm → pneumothorax, pleuritis
- GI arm → GERD, esophageal spasm
- Musculoskeletal arm → costochondritis
- Psychiatric arm → panic disorder

A 22yo female with the same complaint gets different arm weighting and different leading questions. **Patient parameters actively change which arms are prioritized.**

Each question carries a **diagnostic intent** label — what it rules in or out — so the user understands *why*, not just *what*.

**This is the single strongest product insight in the project. Every architectural addition must serve this concept, not dilute it.**

---

## 4. Why this is evidence-grounded, not hallucinated

Medical content correctness requires grounded sources or a human-designed reasoning framework — not free-floating LLM generation.

**Phase 1 (MVP, current):** Hardcode clinical reasoning frameworks into structured prompts — SOCRATES, red-flag checklists per complaint category, standard differential frameworks. Osama (a near-qualified physician) is the domain expert encoding this — that's the credibility moat, not "the AI read a textbook."

**Phase 2 (v2, future):** Layer RAG using real clinical guideline sources (NICE, ESC, AHA, BTS) so outputs can cite sources. Not required for MVP — architecture must make this pluggable later without a rewrite. The `reasoning` field on the Triage Agent's output (Section 6a) is the seam this plugs into.

**Framing constraint:** this tool assists question generation for history-taking — it does NOT diagnose. The human clinician remains the decision-maker at every step.

---

## 5. The interaction model — not a "submit and wait" tool

Conversational and adaptive, not a static form.

1. User types the chief complaint (e.g., "chest pain").
2. Tool asks 2-3 quick tappable clarifying questions (age/sex, duration, obvious red flags) — ~20 seconds.
3. Arms populate progressively via SSE as each agent finishes reasoning — not all at once.
4. User can **activate**, **deprioritize**, or **check off "patient answered"** on each arm's questions.
5. **Live re-scoring (the single most valuable technical feature):** checking off an answer re-triggers the Triage Agent to re-score arm relevance. This is a real agentic feedback loop — agents revise prior output based on new state, not a one-shot linear run. **Protect this at all costs.**
6. Live summary panel builds a running structured case summary as questions get checked off.
7. Export: clean PDF/printable interview sheet with checked answers and summary.

**UI target audience:** must be presentable to a non-technical recruiter or potential client — proper web UI, not a CLI. Polish matters, but see Section 7 for where polish effort should and shouldn't go.

---

## 6. Why this is genuinely "multi-agent," not a prompt-splitting gimmick

To be defensible as "multi-agent," the build must satisfy all four:

1. **Distinct agent roles, narrow scope per agent** — Triage Agent doesn't generate questions; Question Agent doesn't decide arm relevance.
2. **Typed structured contracts between agents** — Pydantic models enforced at every handoff, not raw text re-parsed downstream.
3. **Feedback, not just a straight pipeline** — downstream events (user checking an answer) re-trigger upstream agents to revise output.
4. **Genuine parallelism** — all active arms get questions generated concurrently via `asyncio`, each reasoning independently.

If all four are present, the "multi-agent system" claim is honest in a technical interview. Do not let implementation drift into "one big prompt split into smaller prompts" — that's a pipeline, not an agent system.

### 6a. Explainability — reasoning lives on the Triage Agent's output, not a separate agent

**Decision: enrich the Triage Agent's schema with a `reasoning` field. Do not add a dedicated "Evidence Agent" stage.** A separate sequential agent adds latency (another full round-trip) for value that's cheaper to get by enriching the existing output schema.

```python
DiagnosticArm(
    name="Cardiac",
    relevance_score=0.82,
    reasoning="Age >50, smoker, exertional symptoms"
)
```

This field makes the score defensible instead of a black box, feeds the Trace Viewer (6b) directly, and is the natural seam for RAG-sourced citations in v2 — same field shape, no pipeline restructuring.

### 6b. Observability — Agent Trace Viewer

**The feature that proves the feedback loop is real, not just claimed.** A relevance score silently changing from 0.82 to 0.41 with no visible cause looks like nothing happened.

**Decision: build as a thin UI layer over state already tracked for the re-scoring loop — not new backend infrastructure.** The re-scoring loop already must know "old score, new score, what changed" internally to function; the Trace Viewer surfaces that existing state rather than discarding it.

```
Triage Agent — 6 arms generated
  Cardiac: 0.82
  Pulmonary: 0.65
  GI: 0.44

User answer: "Pain worsens on inspiration"

Re-score triggered →
  Cardiac:              0.82 → 0.41
  Pulmonary Embolism:   0.55 → 0.89
```

Must appear as a visible panel/expandable log in the UI — not buried in dev tools or backend logs. One of the strongest things to show in a recruiter demo: it's the moment "stateful multi-agent" becomes visibly true rather than asserted.

**Explicitly NOT building:**
- A general-purpose session timeline/event log/"replay interview" system — premature infrastructure for a feature that doesn't exist yet. If the Trace Viewer needs minimal state logging, build exactly that much.
- A separate "confidence score" alongside relevance score — no crisp distinct definition exists yet; a second number would be decoration implying rigor without adding it.

---

## 7. Technical architecture (decided)

### Backend
- **FastAPI** — async-native, pairs with concurrent agent calls, built-in Pydantic validation.
- **Plain Python `asyncio`** for orchestration — NOT LangGraph/CrewAI for v1. Hand-rolling means Osama actually understands what's happening, and it's portfolio-honest ("I built the orchestration" vs. "I used a framework's orchestration"). Revisit a framework later only if complexity warrants it.
- **Pydantic models define every agent handoff contract.** Define BEFORE writing any prompts. This is the single most important architectural decision in the project — it's what lets prompting/grounding strategy change later (RAG, different providers) without breaking the pipeline. Must include the `reasoning` field (6a) from the first schema pass. The five locked inter-agent contracts live in `app/models/` (`ClinicalQuestion`, `DiagnosticArm`, `TriageOutput`, `RescoreTrigger`, `ScoreTransition`).
- **One transport-only wrapper model exists OUTSIDE those five, on purpose:** `QuestionList` (defined in `question_generator.py`, not `app/models/`) wraps the Question Generator's single-call response (`list[ClinicalQuestion]`) because `call_agent()` constrains output to exactly one `BaseModel` and JSON-schema can't return a bare top-level array. It's a transport envelope for one API call, immediately unwrapped — NOT an inter-agent handoff contract, and must not be confused with the five locked contracts.
- **In-memory session state for MVP** (simple dict), upgrade path to Redis noted but not required. This state already tracks score transitions for re-scoring — the Trace Viewer (6b) reads from it, no separate storage needed. Implemented as a module-level `dict[str, TriageOutput]` in `main.py`, keyed by a generated session id (Section 12 item 5).

### AI provider layer
- **OpenRouter**, not a single hardcoded provider — lets agents route to different models by task complexity, A/B test quality per agent without touching pipeline code.
- **Critical rule: all AI calls go through ONE abstracted function** — e.g. `call_agent(agent_role, payload) -> ValidatedModel`. Never scatter raw API calls through the codebase.
- **Per-agent model routing:**

| Agent | Task complexity | Suggested tier |
|---|---|---|
| Triage Agent (arm relevance scoring + reasoning, incl. re-scoring) | Medium reasoning, frequent calls | Cheap/fast (Haiku-class) |
| Question Generator Agent (per arm, ×N parallel) | Lower reasoning, templated | Cheap/fast — cost multiplies by arm count, keep cheap |
| Prioritization / Red-Flag Agent | Highest stakes — safety-critical | Stronger (Sonnet-class or better) |

- **The Prioritization / Red-Flag Agent combines re-scoring AND the red-flag safety check into ONE agent call**, not two separate steps — a deliberate scope decision made mid-build, because both judgments need the exact same input (the full current arm-state) and a re-score that ignored red-flag risk would be incomplete on its own. This is a conscious, justified deviation from the narrow-scope-per-agent rule (Section 6, point 1), documented at the top of `prioritization.py`. The red-flag net is honest reasoning text ("cannot be excluded despite low likelihood"), never an inflated score — score stays a pure likelihood.
- No dedicated medical fine-tuned model — general frontier models currently outperform niche medical fine-tunes on structured clinical reasoning. Medical correctness comes from the **hardcoded clinical frameworks in the prompts** (Section 4), not model selection.
- **Cost reality check:** a full interactive session (~20-25k tokens across initial fan-out + several re-scoring triggers) costs roughly $0.05 on a Haiku-class model. Not a constraint at MVP/demo scale. Prompt caching (~90% input cost reduction) is a good future optimization, not needed for v1.

### Frontend-backend communication
- **Server-Sent Events (SSE)** for streaming arm cards as they complete — Osama has production experience with this exact pattern from StudyBuddy's "AI Enhance" sidebar.
- Plain React frontend, consistent with existing stack, calling the FastAPI backend.

### Build priority ranking (engineering value, highest to lowest)
This ordering matters when time is short — reflects where actual technical/portfolio value lives, not where the most visible polish lives:
1. Agent loop (triage → questions → prioritization → re-scoring)
2. State management (session state, score transition tracking)
3. Streaming (SSE arm cards)
4. Observability (Trace Viewer, 6b)
5. PDF export

**PDF export stays in scope but should not absorb significant build time.** Keep it functional and simple — don't over-invest.

---

## 8. Explicitly rejected / shelved ideas (don't re-litigate)

- **Multi-agent medical research summarizer (PubMed-style):** Rejected — Elicit already does this at scale, not a winnable differentiation space.
- **AI flashcard generator from PDF:** Rejected — achievable with one well-crafted prompt, not technically substantial enough.
- **Clinical case anonymizer & structurer:** Not rejected, shelved for a later project. Connects to StudyBuddy's QBank, has real depth — worth returning to.
- **Broad lifestyle/career management app for med students:** Rejected — crowded category, value is UX not technical depth.
- **Dedicated "Evidence Agent" as a separate pipeline stage:** Scaled down to an enriched field on the existing Triage Agent instead (6a) — same value, less latency, less complexity for its own sake.
- **General-purpose Session Timeline / "Replay Interview":** Rejected for v1 — premature infrastructure (6b).
- **Confidence score as a field separate from relevance score:** Rejected for v1 — no crisp distinct definition yet, would read as decorative (6b).

---

## 9. What "done" looks like for v1 / MVP

A working web app where:
1. User enters a chief complaint and answers 2-3 quick clarifying questions.
2. Diagnostic arm cards stream in progressively (SSE), each with prioritized, intent-labeled questions grounded in a hardcoded clinical framework, **each carrying a visible reasoning trail for its score** (6a).
3. User can activate/deprioritize arms and check off answered questions.
4. Checking an answer triggers a real re-scoring call that visibly changes arm priority — **the feedback loop, the must-have** — **and that transition is visible in an Agent Trace Viewer** (6b), not just reflected silently in the UI.
5. A live summary panel builds as the interview progresses.
6. User can export a clean, simple PDF/printable interview sheet (functional, not over-polished).
7. Presentable to a non-technical recruiter without Osama explaining the code — the Trace Viewer is one of the strongest things to show in a live demo.

### Explicitly out of scope for v1
- RAG / live guideline retrieval (v2 — architecture allows it via the `reasoning` field seam)
- Multi-user accounts / persistent storage beyond a session (Redis upgrade path noted, not required)
- Mobile app — web only
- General session timeline/replay (6b)
- Separate confidence scoring (6b)

---

## 9a. Known issues / open threads

**Re-scoring quality with ambiguous patient input (largely addressed — calibration
prompt added, 2026-06-22).** Original observation: during manual UI testing an answer
of "feels like a slap on chest" — intended by the tester to suggest a cardiac-leaning
sensation — was read by the Prioritization Agent as atypical for ACS and Cardiac's
score dropped (0.85 -> 0.75) rather than rose. Root cause confirmed as a prompt-clarity
gap, not a model-capability or re-scoring-logic defect: the system prompt was silent on
how to handle non-standard/colloquial phrasing, so the model fell back to "unfamiliar
-> atypical -> lower."

Fix: an additive "INTERPRETING AMBIGUOUS OR COLLOQUIAL PATIENT LANGUAGE" paragraph was
added to `_build_system_prompt()` in `prioritization.py` (the two-part RE-SCORE /
RED-FLAG framing and the hard-rules list were left untouched). It tells the model to
interpret the most clinically plausible meaning FIRST rather than treating odd wording
as atypicality, to keep "ambiguous, can't move confidently" distinct from "interpreted,
points toward/away," and to SAY in the reasoning when it's genuinely ambiguous rather
than silently picking a direction (same honesty principle as the red-flag check).

Verified live against OpenRouter (not mocked), re-scoring the SAME Cardiac
character-of-pain question for a 60yo male smoker:
- "feels like a slap on chest" → now 0.75 -> 0.70 (a smaller nudge than the original
  0.10 drop), and the reasoning now explicitly names the ambiguity ("the description is
  ambiguous and does not exclude ischemia… cannot be confidently deprioritized on this
  answer alone") and adds a red-flag note ("ACS cannot be excluded in this high-risk
  patient"). The reasoning quality — the actual target of the fix — is materially
  better; it no longer reads as a silent unfamiliar->atypical reflex.
- Clear phrasings still correctly RAISE Cardiac and the new instruction did NOT make
  the model over-cautious: "crushing pressure in the center of my chest" 0.75 -> 0.85;
  "feels like an elephant sitting on my chest" 0.75 -> 0.85 (reasoning explicitly
  recognized it as "classic colloquial language," i.e. colloquial ≠ atypical — the
  exact distinction the fix targets); "heavy tightness… whenever I climb stairs"
  0.75 -> 0.90.

Honest residual: "slap on chest" still drifts down slightly (0.05) rather than staying
flat — but a slap is a genuinely sharp/superficial descriptor, so a small reduction
that is now transparently explained and red-flag-caveated is a defensible read, not the
original silent mis-scoring. Considered addressed for MVP; revisit only if a clearer
counter-example surfaces.

**QUESTION_GENERATION_THRESHOLD — SUPERSEDED (2026-06-22) by top-N lazy generation.**
History (don't re-litigate the earlier steps): originally a 0.4 score threshold as a
cost-control gate; lowered to 0.05 ("effectively always") to force a full concurrent
fan-out and then kept there for a while as full-fan-out behavior. That full fan-out
turned out to be both a cost problem (every active arm fired a real OpenRouter call)
and a UX problem (low-relevance arms — e.g. a 3%-relevance Panic arm — arrived
cluttered with 5 questions nobody asked for). **Decision changed:** the threshold
constant is REMOVED and replaced by `TOP_N_AUTO_GENERATE = 3` (config.py). Only the
top 3 ACTIVE arms by score get questions auto-generated at initial triage; every other
active arm arrives with an empty `questions` list and is generated LAZILY — on demand
when the user expands it (`POST /api/arm/expand`), and automatically if a re-score
later lifts it into the top 3 (handled inside `process_answer`, same call). A single
shared primitive `orchestration.ensure_arm_questions(arm, …)` (idempotent: no-ops if
the arm already has questions) backs all three call sites — initial top-3 fan-out,
on-demand expand, post-rescore promotion — so they can't drift. Note this also
RESOLVES the old "manually promote a deprioritized arm" open question: deprioritized
arms are still gated out entirely (status check is unchanged and independent of the
top-N rank), and the lazy on-demand expand path is now the real mechanism for pulling
in a non-top-3 arm's questions. Verified live (top-3-only initial gen; on-demand expand
+ idempotent repeat; a PE-cue re-score promoting a previously-empty Pulmonary Embolism
arm into the top 3 and auto-generating its 5 questions inside the one /api/answer call;
and a neutral answer re-scoring with zero unnecessary generation).

**Frontend follow-up — DONE (2026-06-22).** The React frontend now wires the
lazy-expand affordance to `POST /api/arm/expand`: `expandArm()` transport in
`client.ts`; `useInterview` holds an `expandingArms: Set<string>` and an `expandArm`
callback (guards: live session, status `ready`, arm active + currently empty + not
already in flight — all mirrors of server-side checks, just to avoid pointless
requests) that POSTs `{session_id, arm_name}` and merges the returned `arm.questions`
into the triage state; `App.tsx`'s Accordion `onValueChange` fires `expandArm` for
arms newly opened by that toggle (batched with the open-state update so the loading
skeleton shows on the next render with no "No questions" flash); `DiagnosticArmCard`
takes an `expanding` prop and shows the same question Skeletons during on-demand load
as during the initial SSE fan-out. Known minor gap (intentional, not worth the
complexity/lint fight): if the user expands a question-less arm during the brief
re-score window, `expandArm` bails (won't mutate the session concurrently with
`/api/answer`); collapsing and re-opening generates it. Verified live: production
build + tsc clean, changed files lint-clean, and the exact same-origin path the UI
uses (`/api/arm/expand` through Vite's dev proxy → backend) returns real generated
questions for a non-top-3 arm.

---

## 10. V2 roadmap (only after MVP succeeds — do not pull forward)

1. **RAG-based guideline support** — NICE, ESC, AHA, BTS as candidate sources. Plugs into the Triage Agent's `reasoning` field without a pipeline rewrite.
2. **Complaint expansion — deliberately slow.** After chest pain (the v1 proof case), add exactly two more: abdominal pain, headache. Three total is enough to prove the architecture generalizes. Resist scaling complaint count before the architecture has actually been proven to generalize.
3. **Clinician personalization** — e.g. "Emergency Physician Mode" vs. "Medical Student Mode" changing question depth. Post-MVP.

---

## 11. How to work with Claude Code on this

- Explain **every architectural decision**, not just deliver working code — especially Pydantic contracts and agent orchestration logic.
- Default to **plain Python/FastAPI patterns over heavy frameworks** unless there's a clear reason otherwise.
- Surface model/provider choices as **named constants or config, not hardcoded inline strings** — model swapping per agent is expected.
- **When in doubt about a clinical framework detail** (e.g., what counts as a red flag for a given complaint), ask Osama — he's the domain expert, this is the one area where he drives content.
- **Filter for every future feature suggestion** (from audits, from Osama, from anywhere): does this add genuine capability, or does it add complexity/agent-count/infrastructure for the sake of looking sophisticated? Prefer enriching what exists over adding new pipeline stages unless there's a clear functional reason a new stage is required.

---

## 12. Build sequence (current state — update this section as steps complete)

1. ☑ Finalize Pydantic data contracts between Triage Agent (incl. `reasoning` field) → Question Generator Agent(s) → Prioritization Agent → re-scoring loop. (`backend/app/models/`: `clinical.py`, `triage.py`, `trace.py`, re-exported from `__init__.py`.)
2. ☑ FastAPI project folder structure scaffolded.
3. ☑ Build the abstracted `call_agent()` function wrapping OpenRouter, with per-agent model routing as config. (`backend/app/core/call_agent.py`; routing constants in `config.py`; schema-constrained structured outputs, fail-loud no-retry. Verified live against OpenRouter.)
4. ☑ Hardcode the first clinical framework for ONE complaint (chest pain — canonical teaching example, well-known diagnostic arms) to validate the full pipeline end-to-end before generalizing. **Done — full single-complaint pipeline works end-to-end and is verified live via `_run_pipeline.py`:** chest pain framework (`backend/app/agents/frameworks/chest_pain.py`) → Triage Agent (`backend/app/agents/triage.py`) → Question Generator Agent (`backend/app/agents/question_generator.py`) + concurrent orchestration (`backend/app/core/orchestration.py`, genuine `asyncio.gather` fan-out) → Prioritization/re-score + red-flag Agent (`backend/app/agents/prioritization.py`) + feedback-loop orchestration (`backend/app/core/rescore.py`). The re-scoring loop produces real `ScoreTransition` records and the red-flag check surfaces as honest "cannot be excluded despite low likelihood" reasoning on dropped can't-miss arms (score stays an honest likelihood, never inflated).
5. ☑ Wrap the working pipeline in a FastAPI layer and make it reachable/visible.
   - ☑ First HTTP layer: `POST /api/triage` and `POST /api/answer` added to `main.py`,
     plain request/response (no streaming yet). Verified live against the real
     OpenRouter backend — health check, full triage+question-gen fan-out, a real
     re-score via a typed answer, and a deliberately-bad session_id correctly
     returning a clean 404 (and a bad question_id a clean 400), not an opaque 500.
   - ☑ First visible UI: a throwaway plain HTML/JS demo page at
     `backend/app/static/demo.html`, served same-origin (no CORS needed) via a
     dedicated `GET /demo.html` `FileResponse` route — deliberately a route, NOT a
     `StaticFiles` mount, to keep the exact top-level URL and avoid a catch-all
     mount shadowing `/api/*`. Manually tested end-to-end: real chest pain scenario,
     real typed answers, arm cards update with new scores/reasoning, and a manual
     trace log on the page shows each `ScoreTransition` (old score -> new score,
     triggering answer text), accumulating across multiple answered questions in one
     session. Explicitly disposable — will be replaced by the real React frontend,
     not iterated on further.
   - ☑ SSE streaming: `GET /api/triage/stream` (added to `main.py`) now reveals arm
     cards progressively instead of one all-at-once pause. It emits `event: triage`
     (all arms scored, questions still empty) the moment `run_triage()` returns, then
     one `event: arm_questions` per arm as each one's questions land, then `event:
     done` carrying the `session_id` (the fully-populated `TriageOutput` is stored in
     `_SESSIONS` here); any failure emits `event: error` with a JSON `detail` and ends
     the stream cleanly. The progressive delivery comes from a new
     `populate_questions_streaming()` async generator in `orchestration.py` that swaps
     `asyncio.gather` for `asyncio.as_completed` — the SAME concurrent fan-out, but
     yielding each `(arm, questions)` pair in completion order as it finishes (the
     qualifying-arm filter is shared with `populate_questions()` via a `_qualifying_arms`
     helper, not duplicated). The throwaway `demo.html` start flow now consumes this
     via `EventSource` (scored cards on `triage`, questions appended per `arm_questions`,
     no full re-render). The non-streaming `POST /api/triage` is kept as-is for
     tests/scripts. `POST /api/answer` was deliberately NOT streamed — re-scoring is a
     single combined agent call (Section 7), so there is no progressive reveal to
     stream. Verified live against OpenRouter: `triage` event at ~12s, `arm_questions`
     staggered ~20.1s → ~23.5s across 7 arms in completion order (not one batch), `done`
     with a session id; a follow-up `POST /api/answer` on the streamed session still
     re-scored correctly (7 transitions); and a deliberately-bad model slug produced a
     clean `event: error` in the client rather than a silently dropped connection.
   - ☑ Top-3 auto-generate + lazy generation, and the on-demand expand route
     (2026-06-22, supersedes the old full-fan-out threshold — see Section 9a). Initial
     triage now only auto-generates questions for the top `TOP_N_AUTO_GENERATE` (=3)
     ACTIVE arms by score (`orchestration._qualifying_arms` now means "top-N active",
     not "above threshold"); every other active arm arrives with an empty `questions`
     list. Two ways the rest get filled lazily, both routed through ONE shared
     idempotent primitive `orchestration.ensure_arm_questions(arm, …)` (no-ops if the
     arm already has questions): (1) **`POST /api/arm/expand`** — new route in
     `main.py`, body `{session_id, arm_name}` (arm_name in the BODY, not the path,
     because arm names contain spaces/parens/slashes like "Cardiac (ACS / Ischemic)";
     also matches the existing `/api/answer` body convention), looks the arm up by
     name, ensures its questions, saves back to the session, returns `{arm}` — a
     harmless no-op (not an error) if already populated, so the frontend can call it
     defensively; (2) **post-rescore promotion** — `process_answer` now re-evaluates
     the top-3 AFTER merging new scores and auto-generates questions for any arm newly
     in the top-3 that still has none, inside the SAME `/api/answer` call, so the
     caller just sees one consistent state. This required threading `patient_context`
     into `process_answer` (and storing it on the session: `_SESSIONS` now holds a
     small `_Session(triage, patient_context)` dataclass instead of a bare
     `TriageOutput`) so lazily-generated arms are tailored to the same patient as the
     initial fan-out. SSE/`/api/triage`/`/api/answer` response SHAPES are unchanged —
     non-top-3 arms simply carry an empty `questions` list, which the contract already
     allows; the only visible difference on the stream is that fewer `arm_questions`
     events fire at initial-triage time (top-3 only). **Frontend follow-up — now DONE
     (2026-06-22):** the React UI calls `/api/arm/expand` when the user expands a
     question-less arm (skeleton → questions); see the Section 9a "Frontend follow-up"
     note for the wiring details. Verified live against
     OpenRouter (chest pain, 60yo male smoker): top-3 = Cardiac/Aortic/PE got 5
     questions each, the other 4 arms got 0; expanding Pneumothorax generated 5 and a
     repeat call returned the identical 5 ids (true no-op); a PE-cue answer in a fresh
     session dropped Cardiac 0.75→0.35 and raised PE 0.15→0.85, promoting a
     previously-EMPTY Pulmonary Embolism into the top-3 and auto-generating its 5
     questions inside the one `/api/answer` call; and a neutral answer re-scored (2
     transitions) with zero unnecessary generation.
6. ☑ Build minimal state tracking for re-scoring transitions, surfaced via a simple Trace Viewer panel (6b) as soon as the re-scoring loop works — not left until the end. **Done.** Data side was already done (`process_answer()` returns `list[ScoreTransition]`, changed-arms-only). The Trace Viewer is now a **real React component** (`frontend/src/components/TraceLogPanel.tsx`), not demo.html's hand-rendered log — it reads the `transitions` the `POST /api/answer` route already returns; zero backend work was needed. Built as part of the real frontend scaffold:
   - **Stack:** Vite + React 19 + TypeScript + Tailwind v4 + shadcn/ui (initialized via `npx shadcn@latest init`; primitives added via `npx shadcn@latest add …` — accordion, skeleton, input, textarea, card, badge, button — never hand-copied). NOTE: this shadcn version is built on **Base UI** (`@base-ui/react`), not Radix, and uses **lucide-react** for icons — relevant because the Accordion's controlled API is `value`/`onValueChange`/`multiple` (Base UI), not Radix's `type="single|multiple"`. `@/` path alias is configured WITHOUT `baseUrl` (TS 6 deprecates it; `paths` + `moduleResolution: "bundler"` resolve fine). Lives in `frontend/`; the throwaway `backend/app/static/demo.html` is now superseded (kept, not iterated on).
   - **Dev wiring:** Vite `server.proxy` forwards `/api/*` → `http://127.0.0.1:8000` so the frontend develops same-origin against the real backend (no CORS), mirroring how `demo.html` is served. Production serving strategy intentionally NOT decided here. `main.py` static serving was NOT touched.
   - **Design system (Sustainable Energy / Climate Tech):** mapped into shadcn's CSS-variable convention in `src/index.css` (`:root` + a full `.dark` block, even though no toggle ships yet) — `--primary` `#059669`, `--background` `#ECFDF5`, `--foreground` `#064E3B`, `--border`/`--accent` `#A7F3D0`; the palette's secondary `#10B981` and a clinical red-flag colour live as custom `--brand-secondary`/`--flag` tokens (used by the gauge gradient, "Live" status dot, and red-flag reasoning) rather than hardcoded hex in components. NOTE: shadcn's `--accent` token is the *hover surface* (light tint), which is NOT the palette's brand "accent" — that maps to `--primary`. Typography is the "Corporate Trust" pairing — **Lexend** headings, **Source Sans 3** body — self-hosted via Fontsource (same mechanism shadcn used for its default Geist, which was removed).
   - **Components:** `ComplaintBar` (hero ↔ docked: same inputs never unmount/remount, the dominant motion is a `translateY` transform per ux-guidelines row 13, with a ResizeObserver feeding the page's top padding so cards never hide behind the fixed bar); `DiagnosticArmCard` (a card-styled Accordion item — `Accordion` is controlled, `multiple`, open-set = arm names); `ScoreGauge` (circular 0–1 ring, brand gradient, CSS-animated `stroke-dashoffset` so a re-score sweeps old→new); `ScoreTransitionIndicator` (transient strikethrough-old → arrow → new pill, self-fades ~2.5s); `QuestionRow` (distinct answered/unanswered states); `StreamingStatus` ("Live Data"-style chip mirroring the real SSE sequence); `TraceLogPanel` (the Trace Viewer, newest-first like demo.html). All TS types in `src/types.ts` mirror the Pydantic contracts field-for-field; all data flows through one `useInterview` hook (`src/hooks/useInterview.ts`) and the `src/api/client.ts` transport (EventSource + fetch).
   - **Leader auto-expand (6b's most specific UI rule):** the highest-scoring arm is "the leader"; on each data update (`arm_questions` events and every `/api/answer` re-score) `useInterview` diffs previous vs current leader in a `useEffect` (data-driven, not inside the Accordion's click handler). On an actual leadership change it touches ONLY two arms — expand the new leader, collapse the old — leaving every other arm's manual open/closed state alone. Ties / score-decreases that don't change who's on top do NOT fire it (`computeLeader` keeps the prev leader when it still shares the max).
   - **Verified live** against the real running backend (FastAPI + Vite side by side, driven through Chrome via Playwright, no mocked responses): hero docks on submit; SSE streams scored cards → per-arm questions (Skeletons while pending) → Ready; the initial top arm (Cardiac) auto-expands; answering a Pulmonary Embolism question with a pleuritic/DVT cue re-scored PE 0.10→0.85 and Cardiac 0.92→0.65, and **the new leader (PE) auto-expanded while the old leader (Cardiac) auto-collapsed and a separately, manually-opened arm stayed exactly as left** — with the old→new indicator on PE's gauge, a new Trace Viewer entry, and the "Leading" badge moved to PE. No horizontal overflow at 390px. (11/12 scripted assertions passed; the 12th was a test-selector artifact — `hasText:"Cardiac"` also matched PE's reasoning text — not an app defect, since `leaderName` is a single value so only one arm can ever show "Leading".)
7. ☐ Only after the single-complaint pipeline works end-to-end (re-scoring loop + Trace Viewer working) — generalize to additional complaints per the slow V2 roadmap (Section 10).

**Next concrete task: item 7 — generalize beyond chest pain, but ONLY per the deliberately-slow V2 roadmap (Section 10): add abdominal pain, then headache; three complaints total is enough to prove the architecture generalizes. Do not pull forward RAG or scale complaint count before the architecture is proven to generalize.** Everything up to and including the real React frontend + Agent Trace Viewer is now done and verified live end-to-end. The frontend (`frontend/`) is free text → the existing chest-pain-tuned pipeline; it does NOT hardcode a complaint list, so adding complaints is purely a backend framework/agent concern (Section 7), and the frontend should keep working unchanged as long as the SSE/answer contracts hold. Useful current entry points: `frontend/src/hooks/useInterview.ts` (all client state + leader logic), `frontend/src/api/client.ts` (SSE + answer transport), `frontend/src/types.ts` (contract mirrors). Run locally with the FastAPI backend on :8000 and `npm run dev` in `frontend/` (Vite proxies `/api/*`).
