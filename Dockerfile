# Multi-stage build for the single-container public demo (deploy-hardening): ONE FastAPI
# process serves both the JSON/SSE API under /api/* and the built React frontend at /,
# same origin. Stage 1 builds the Vite frontend; stage 2 is the Python runtime that
# installs backend deps from pyproject.toml and copies the built frontend in.

# ---- Stage 1: build the frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Produces /app/frontend/dist (Vite's default outDir — vite.config.ts sets no override).

# ---- Stage 2: Python runtime serving both API and built frontend ----
FROM python:3.13-slim AS runtime
WORKDIR /app

# Install backend deps from pyproject.toml. README.md is copied alongside it because
# pyproject declares `readme = "README.md"`, which the build reads — without it
# `pip install .` fails on missing metadata. At this point only these two files exist in
# the context, so setuptools' flat-layout auto-discovery finds no package and the install
# is effectively "just the declared dependencies".
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Most hosts (Railway/Render/Fly) inject $PORT at runtime; default to 8000 for a local
# `docker run`. WORKDIR backend so `app.main:app` resolves on the import path.
ENV PORT=8000
EXPOSE 8000
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
