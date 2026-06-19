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
- **Pydantic models define every agent handoff contract.** Define BEFORE writing any prompts. This is the single most important architectural decision in the project — it's what lets prompting/grounding strategy change later (RAG, different providers) without breaking the pipeline. Must include the `reasoning` field (6a) from the first schema pass.
- **In-memory session state for MVP** (simple dict), upgrade path to Redis noted but not required. This state already tracks score transitions for re-scoring — the Trace Viewer (6b) reads from it, no separate storage needed.

### AI provider layer
- **OpenRouter**, not a single hardcoded provider — lets agents route to different models by task complexity, A/B test quality per agent without touching pipeline code.
- **Critical rule: all AI calls go through ONE abstracted function** — e.g. `call_agent(agent_role, payload) -> ValidatedModel`. Never scatter raw API calls through the codebase.
- **Per-agent model routing:**

| Agent | Task complexity | Suggested tier |
|---|---|---|
| Triage Agent (arm relevance scoring + reasoning, incl. re-scoring) | Medium reasoning, frequent calls | Cheap/fast (Haiku-class) |
| Question Generator Agent (per arm, ×N parallel) | Lower reasoning, templated | Cheap/fast — cost multiplies by arm count, keep cheap |
| Prioritization / Red-Flag Agent | Highest stakes — safety-critical | Stronger (Sonnet-class or better) |

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

1. ☐ Finalize Pydantic data contracts between Triage Agent (incl. `reasoning` field) → Question Generator Agent(s) → Prioritization Agent → re-scoring loop.
2. ☑ FastAPI project folder structure scaffolded.
3. ☐ Build the abstracted `call_agent()` function wrapping OpenRouter, with per-agent model routing as config.
4. ☐ Hardcode the first clinical framework for ONE complaint (chest pain — canonical teaching example, well-known diagnostic arms) to validate the full pipeline end-to-end before generalizing.
5. ☐ Get SSE streaming of arm cards working against this one hardcoded case before building out React UI polish.
6. ☐ Build minimal state tracking for re-scoring transitions, surfaced via a simple Trace Viewer panel (6b) as soon as the re-scoring loop works — not left until the end.
7. ☐ Only after the single-complaint pipeline works end-to-end (re-scoring loop + Trace Viewer working) — generalize to additional complaints per the slow V2 roadmap (Section 10).

**Next concrete task: item 1 — Pydantic contracts.**
