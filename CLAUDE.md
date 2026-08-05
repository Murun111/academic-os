# Academic OS

Student planning hub. 5 modules (applications, courses, study, documents, routines) share a unified agenda and agent-driven automations.

## Stack + commands

**Backend:** Python 3.14 · FastAPI 0.115.0 · uvicorn · venv at `.venv`.

**Frontend:** React 19 · Vite 6.3 · Tailwind 4.1 · npm.

Commands:
- Backend dev: `ACADEMIC_OS_DATA=~/.academic-os .venv/bin/uvicorn backend.app:app --port 7878`
- Tests: `.venv/bin/python -m pytest tests/ -q` (full suite green as of 2026-07-30; legacy agentic-os tests were removed in the fork cleanup)
- Frontend dev: `cd webui && npm run dev`
- Frontend typecheck: `npx tsc -b`
- Frontend build: `VITE_API_MODE=real npm run build` (outputs to `webui/dist`)
- Seed demo data: `python scripts/seed_demo.py`

## Gotchas

**Data root:** `~/.academic-os` (or env `ACADEMIC_OS_DATA`). Functions `resolve_vault_path()` and `agentic_os_dir()` in `backend/vault.py` kept from fork for compatibility.

**Forked from agentic-os:** Never re-add deleted services by "fixing imports." Deleted services are gone intentionally.

**Cross-module contract:** StudyService / routines import ApplicationsService.upcoming_deadlines + CoursesService.due_soon, guarded by try/except (best-effort aggregation if either service down).

**Router order:** Literal paths like `/api/study/agenda` register BEFORE `/{id}` routes or they get shadowed.

**Agenda cap:** `days` query param capped at 90 (router validation).

**Ollama optional:** LLM endpoints degrade to 503 if Ollama unreachable. Webui pages handle gracefully.

**Tailwind 4:** No `tailwind.config.js`. All tokens live in `webui/src/index.css` under `@theme { }` block.

**Frontend API clients:** Each page owns a self-contained `<module>Api.ts` (e.g., `studyApi.ts`, `coursesApi.ts`). Not centralized in `lib/api.ts`.

**Stage-aware UI:** every per-stage difference lives in `webui/src/lib/stageConfig.ts` as data — never `if (stage === ...)` in components. `useState(cfg.X)` captures the pre-onboarding fallback; sync with a `useEffect` on the cfg value.

**Track-aware UI:** second axis (pre-med/pre-law/…) in `webui/src/lib/trackConfig.ts`, same data-only rule. Only applies when `trackApplies(stage)` (undergrad/beyond). Track overrides layer on top of stage config (`trackCfg?.x ?? cfg.x`).

**Dev backend has no --reload:** after editing backend code, kill the uvicorn on 7878 and restart it — the old process silently serves stale code (pydantic drops unknown fields, so new profile fields "vanish" on save).

**Agent tools:** `web.search`/`web.fetch` are plain-httpx (no camofox) and classified read-only in `autonomy.py`'s `_READ_SET`; `academics.add_application` is deliberately unlisted so the cautious posture gates it → Approvals queue. Approving executes the tool.

**Agent run API:** run reply field is `id` (not `run_id`); the output field is `result`.

**ICS sync:** upserts by `external_id` (ICS UID); never writes `status`/`grade`/`notes` on existing assignments (student-owned). `add_course` requires a non-empty `term` — synced courses use `"Synced"`.

**Launcher:** `scripts/start.command` — double-clickable, first run creates the venv, close window to quit.

## Architecture

**Backend:**
- `backend/app.py` — FastAPI shell: mounts 5 academic routers, LLM hub, memory, agent runner/scheduler, approvals, WebSocket events
- `backend/routers/` — 5 modules: applications, courses, study, documents, routines
- `backend/services/` — module services + kept infra (agent_runner, scheduler, calendar, inbox, browser, llm_hub, memory, tools)
- Storage: JSONL per module under data root (data/applications/*, data/courses/*, etc.)

**Frontend:**
- `webui/src/pages/` — 10 pages: Applications, Courses, Study, Documents, Routines, Dashboard, Chat, Agents (labeled "Assistants" in UI), Approvals, Settings (gear at sidebar bottom: name, stage, LocalAiPanel, LmsSyncPanel, data-folder note). Memory/Traces pages removed 2026-08-04 (student-facing cut); backend /api/memory + traces endpoints kept (agent runner + Chat recall use them)
- Profile PUT replaces the whole profile.json — store.ts always sends name alongside stage (setStage used to wipe the name)
- `webui/src/lib/` — module API clients (applicationsApi.ts, coursesApi.ts, etc.)
- Build output: `webui/dist/` (served by FastAPI at `/`)

## Deploy + env

Localhost only (no deploy yet). Optional `.env` file in `backend/` (copy from `.env.example`).

Environment variables:
- `ACADEMIC_OS_DATA` — data root (default: `~/.academic-os`)
- `OLLAMA_BASE_URL` — Ollama server (default: `http://localhost:11434`)
- `OLLAMA_DEFAULT_MODEL` — LLM to warm on startup (default: `gemma4:latest`)
- `BIND_PORT` — HTTP listen port (default: `7878`)

Frontend must be built (`npm run build`) for the backend to serve it at `/`. Dev flow uses Vite proxy to `http://localhost:7878` for `/api` and `/ws`.
