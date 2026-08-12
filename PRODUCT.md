# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Students, distributed broadly. The person using this is someone the author will never meet, so
onboarding, empty states, and stage/track generality are load-bearing rather than optional.

Five life stages are first-class and **equally weighted** — none is the "real" one the others
degrade from:

| Stage | The job they're doing |
|---|---|
| High school | Applying to colleges and scholarships |
| Undergrad | Courses now, internships and what comes next |
| Gap year | Graduated, working or studying for the next step |
| Grad school | Programs, funding, and the SOP grind |
| Beyond | Fellowships, research, and career moves |

A second axis applies only to undergrad, gap year, and beyond: pre-med (MCAT), pre-law (LSAT),
pre-dental (DAT), grad school (GRE), or not-sure. "Not sure yet" is a real, supported answer that
means no tailoring, not an unfinished profile.

## Product Purpose

A student planning hub. Five modules — applications, courses, study, documents, routines — share a
unified agenda and agent-driven automations, so deadlines, coursework, and application milestones
live in one place instead of scattered across a calendar, a notes app, and a spreadsheet.

Success is a student trusting it enough to keep their real deadlines in it.

## Positioning

It runs entirely on the student's own machine, and it ships its own inference to keep that true.
Data lives in `~/.academic-os` as plain JSONL. The distributable bundles llama.cpp (`vendor/llama`,
~52 MB) so the assistant works without an account, an API key, or a network. When no model is
reachable, LLM endpoints return 503 and the pages handle it — they do not fall back to a hosted
model.

A neighboring planner cannot truthfully claim that a student's applications, essays, and academic
record never leave their computer.

## Operating Context

- Localhost only. FastAPI serves the built frontend at `/` on port 7878 (`BIND_PORT`).
- Two launch paths: `scripts/start.command` for source checkouts (creates the venv on first run,
  close the window to quit), and the packaged `Academic OS.app` for everyone else.
- Storage is JSONL per module under the data root. No database service to install or run.
- Local inference is optional-by-necessity: bundled llama.cpp, or an Ollama instance at
  `OLLAMA_BASE_URL`. Surfaces that use the LLM must stay usable, visibly, when neither answers.
- ICS calendar sync pulls courses and assignments by external UID, and never overwrites
  student-owned fields (status, grade, notes) on records that already exist.

## Capabilities and Constraints

**Confirmed capabilities**

- Ten pages: Applications, Courses, Study, Documents, Routines, Dashboard, Chat, Agents (labeled
  "Assistants" in the UI), Approvals, Settings.
- Agent runner with an Approvals queue. Read-only tools run unattended; `academics.add_application`
  is deliberately gated so a cautious posture routes it to Approvals before it can write.
- Memory with a privacy view in Settings: list, delete, forget-all.
- Agenda queries capped at 90 days.
- Stage and track differences live as data (`stageConfig.ts`, `trackConfig.ts`), never as
  conditionals inside components. Adding a stage must not mean rewriting surfaces.

**Binding constraints**

- **Nothing leaves the machine.** No cloud sync, no hosted backend, no hosted LLM, not later and
  not as an opt-in. Future work must design around this rather than treat it as a current
  limitation.
- The DMG is unsigned. First launch on another Mac requires right-click → Open. Signing and
  notarization need an Apple Developer account that does not exist yet, so this is the real
  first-run experience for every recipient.
- Memory and Traces pages were removed 2026-08-04 as a deliberate student-facing cut. The backend
  endpoints remain for the agent runner and Chat recall; do not restore the pages as a "fix".

**Explicitly undecided — do not silently resolve**

- No accessibility standard or target has been set. No product-specific user need is on record.
- No distribution channel is chosen. A DMG exists; how a student finds or receives it does not.
- Windows and Linux are unaddressed. The packaging path is macOS-only today, and whether that is
  permanent is undecided.

## Evidence on Hand

Real, verifiable artifacts:

- `dist/AcademicOS.dmg` — 59 MB packaged build, produced 2026-08-04 by `scripts/build_dmg.sh`.
- `dist/Academic OS.app` — the frozen PyInstaller app it wraps.
- Test suite under `tests/`, recorded green as of 2026-07-30 in `CLAUDE.md`.
- `scripts/seed_demo.py` — generates demo data, so screenshots and walkthroughs can use populated
  states rather than invented ones.
- `examples/agents` — shipped agent definitions.

Absences future work must not paper over: there are **no users yet**, no testimonials, no case
studies, no benchmarks, no pricing, and no press. Any surface needing social proof has none
available and must not invent it.

## Product Principles

1. **Nothing leaves the machine.** This is the product, not a setting. It constrains every feature
   that would otherwise reach for a network.
2. **No stage is second-class.** A high-school applicant and a PhD candidate both get a first-class
   surface. Work that only feels right for undergrads is unfinished.
3. **The student is a stranger.** No surface may assume context the author happens to have. Empty
   states, first-run, and unset profiles are primary states, not edge cases.
4. **Degrade visibly, never silently.** Missing model, missing network, missing data — the UI says
   so plainly. Silence reads as breakage and costs the trust the product depends on.
5. **Difference is data, not branching.** Stage and track variation lives in config. A new stage or
   track should be an entry, not a refactor.
