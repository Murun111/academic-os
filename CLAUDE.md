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

**Theming:** light + dark via `:root[data-theme='dark']` var overrides in index.css. Never write `bg-black/N` etc. in components — use `ink/N` (`--color-ink`: black in light, white in dark). Literal `black/` is reserved for modal scrims and the tour overlay only. Toggle lives in Settings; persisted in localStorage `academicos.theme`.

**Frontend API clients:** Each page owns a self-contained `<module>Api.ts` (e.g., `studyApi.ts`, `coursesApi.ts`). Not centralized in `lib/api.ts`.

**Stage-aware UI:** every per-stage difference lives in `webui/src/lib/stageConfig.ts` as data — never `if (stage === ...)` in components. `useState(cfg.X)` captures the pre-onboarding fallback; sync with a `useEffect` on the cfg value.

**Track-aware UI:** second axis (pre-med/pre-law/…) in `webui/src/lib/trackConfig.ts`, same data-only rule. Only applies when `trackApplies(stage)` (undergrad/beyond). Track overrides layer on top of stage config (`trackCfg?.x ?? cfg.x`).

**Chat has TWO Ollama clients:** the Chat tab goes through `llm_hub.OllamaBackend`; essay feedback/agents go through `backend/ollama.py OllamaService`. Both must carry the bundled-llama fallback — a fix in one does not fix the other. Chat threads live at `<root>/data/llm_threads/` via `_threads_dir()` (`THREADS_DIR` is a test override, None in prod — was hardcoded `~/.agentic-os/`, never reintroduce).

**Tests are data-root isolated in conftest:** autouse `_isolate_data_root` points ACADEMIC_OS_DATA at tmp for every test. Before it existed, suite runs wrote real thread files into the user's data root.

**Memory lives in the data root:** index at `<root>/data/memory/index.db`, notes under `<root>/notes/memory/`. `memory_index.DB_PATH`/`trajectory_memory.DB_PATH` are test overrides (None in prod — resolved via vault). The fork originally hardcoded `~/.agentic-os/` — never reintroduce that. Settings has the privacy view (list/delete/forget-all via /api/memory/items).

**Kill by exact PID, not `lsof -ti:PORT | head -1`:** Chrome connections also show up on the port — killing the first PID can leave the old server running and serving stale routes (SPA catch-all answers unknown /api paths with HTML).

**Dev backend has no --reload:** after editing backend code, kill the uvicorn on 7878 and restart it — the old process silently serves stale code (pydantic drops unknown fields, so new profile fields "vanish" on save).

**Data-format stamp:** `data/format.json` written by `data_format.ensure_stamp()` at startup. If `format_version` on disk > `CURRENT_FORMAT`, an app.py middleware 409s every non-GET /api call (except /api/meta) and the webui shows a top banner — protects against older builds silently dropping fields via the defensive `from_dict` pattern. Bump `CURRENT_FORMAT` only when a JSONL schema change is not backward-safe.

**Restore:** `backup.run_restore()` mirrors `<backup>/AcademicOS-Backup/{data,notes,agents}` back over the live root (including deletions) but first snapshots live state to `<root>/pre-restore-snapshots/<ts>/` (3 newest kept). `data/backup.json` always shows as 1 "overwrite" in preview right after a backup (last_backup is stamped after the copy) — cosmetic, known.

**Archive, not delete:** `archived: bool` on Application and Course. Backend aggregations (`upcoming_deadlines`, `due_soon`) skip archived; `list` endpoints return everything and the frontend filters (Applications tab strip, Courses archived section, Dashboard, Calendar). Export intentionally includes archived.

**GPA:** pure frontend math in `webui/src/lib/gpa.ts` (letter scale, credit-weighted term GPA, `neededOnFinal`). `Course.credits` is optional — blank counts as `DEFAULT_CREDITS` (3). No GPA endpoint on the backend.

**Autonomy allowlist:** moved from fork-era `~/.agentic-os/autonomy_allow.json` to `<root>/data/autonomy_allow.json`, with one-time copy migration (legacy never deleted). Test override: `agent_admin._ALLOW_FILE_OVERRIDE` / `autonomy._ALLOW_PATH_OVERRIDE`.

**Credentials are fenced:** `data/connectors/` (Canvas token) is never mirrored by backup, never touched by restore, and `vault_read` returns `forbidden` for it (plus `path_escape` for `../` — mirror both guards in any new path-taking agent tool).

**Config writes are atomic:** every config file (backup.json, canvas.json, ics.json, profile.json, allowlist) writes tmp + `os.replace`. New config files must follow the pattern; a bare `write_text(json.dumps(...))` on a config file is a bug.

**Canvas sync errors are classified:** results carry `error_kind` (auth_error/network_error/canvas_error) + optional HTTP `status`; LmsSyncPanel maps kinds to friendly copy. Whole sync wrapped in a 120s `asyncio.wait_for`. New sync steps must classify their failures.

**Deep-link contract:** `/applications?open=<id>` preselects a card, `/courses?open=<courseId>` expands a course — Calendar, Dashboard, and CommandPalette send these; the two pages read them via `useSearchParams` and clear with `replace: true`.

**Bundled models are sha256-pinned** in `local_llm.MODELS`, verified post-download (mismatch deletes + errors, safe retry). New models need their hash from HuggingFace (tree API `lfs.oid`).

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
