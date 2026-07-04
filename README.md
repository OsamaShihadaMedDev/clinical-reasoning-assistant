# Clinical Reasoning Assistant

A **stateful multi-agent orchestration system** built in Python, using clinical history-taking as the domain. Given a patient's chief complaint, it branches the problem into **diagnostic arms** (pathophysiological categories), generates targeted history questions under each arm weighted by relevance to the specific patient, and **live re-scores** those arms as the clinician checks off answers — a genuine agentic feedback loop, not a one-shot pipeline.

> This is a systems-design project that happens to use medicine as its domain — not "a medical app with AI in it." The headline skills are agent orchestration, state management, and typed contracts between agents. The clinical domain is the proof of depth: it's encoded by a final-year medical student, not scraped from a textbook.

**This tool assists question generation for history-taking. It does not diagnose. The clinician remains the decision-maker at every step.**

## How it works

1. Clinician enters a chief complaint (e.g. "chest pain").
2. A few quick clarifying inputs (age/sex, duration, red flags) refine the picture.
3. Diagnostic arms populate progressively over **Server-Sent Events** as each agent finishes reasoning.
4. Each question carries a **diagnostic intent** — what it rules in or out — so the clinician sees *why*, not just *what*.
5. Checking off an answer **re-triggers upstream agents** to re-score arm relevance in light of the new state. This live re-scoring is the core technical feature.

## Why it's genuinely multi-agent

Distinct, narrow-scope agents (Triage, Question Generator, Prioritization, Suggestion, Investigation, Framework, History) communicate through **typed Pydantic contracts** at every handoff — never re-parsed raw text. Active arms are reasoned over concurrently with `asyncio`, and downstream events feed back to revise upstream output. Each agent is routed to a deliberately chosen model tier (cheap/fast for frequent low-stakes calls, stronger models for safety-critical or cache-once-forever generation).

## Tech stack

**Backend:** Python 3.13 · FastAPI · Uvicorn · httpx · Pydantic · `uv` · OpenRouter
**Frontend:** React 19 · TypeScript · Vite · Tailwind CSS v4 · shadcn/ui · lucide
**Deploy:** Single Docker container serving the built frontend and the API from one origin

## Running locally

**Backend**
```bash
cd backend
cp .env.example .env        # add your OPENROUTER_API_KEY
uv sync
uv run uvicorn app.main:app --reload
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

You'll need an [OpenRouter API key](https://openrouter.ai/keys). It is read server-side from `.env` and never shipped to the browser.

## Docker

```bash
docker build -t clinical-reasoning-assistant .
docker run -p 8000:8000 -e OPENROUTER_API_KEY=your_key clinical-reasoning-assistant
```

A multi-stage build compiles the React frontend and serves it alongside the FastAPI API from a single origin.

## Roadmap

- **RAG grounding (v2):** cite real clinical guidelines (NICE, ESC, AHA, BTS) via the existing `reasoning` field on each arm — the seam is already built in.
- **Agent Trace Viewer:** surface the old-score → new-score transitions the re-scoring loop already tracks, making the feedback loop visible.

## About

Built by a final-year medical student and solo developer of [StudyBuddy AI](https://studybuddyai.com), a live AI medical-education platform with a QBank, AI study-sheet generator, and paying users. This project sits at the intersection of clinical workflow knowledge and systems engineering.
