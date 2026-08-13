# Academic OS

A planning app for students. Applications, courses, essays, scholarships, and deadlines in one place, running entirely on your own computer.

There is no account and no cloud. Your data lives in a folder on your machine (`~/.academic-os`), and the built-in AI runs locally after a one-time model download. Nothing you type leaves your computer.

## What it does

- **Applications board.** Track colleges, scholarships, grad programs, and exchange programs on a drag-and-drop pipeline: researching, preparing, submitted, interview, decision. Each card holds a checklist, deadline, fees, award amounts, notes, and linked essays. A one-click FAFSA card comes with the real checklist and the real deadline.
- **Courses and grades.** Connect Canvas with a token and your courses, assignments, and grades sync automatically. Or add them by hand. A term GPA and cumulative GPA are computed for you, including the "what do I need on the final" calculator.
- **Essays.** Write drafts in the app, keep version history, attach files (transcripts, certificates, PDFs), and get feedback from an essay coach built on the Harvard College Writing Center's guidance. Essays link to the applications they belong to.
- **Deadlines everywhere.** A unified calendar, a next-7-days agenda, daily reminder notifications, and a dashboard that answers "what do I do today."
- **Assistants.** A scholarship scout that searches trusted sources against your profile, and a deadline watcher. Anything an assistant wants to change goes through an approval queue first.
- **Counselor export.** One page with your college list, costs, checklist progress, and grades, formatted for printing.

## Install

Download the latest release from [Releases](https://github.com/Murun111/academic-os/releases/latest).

**Mac:** open the DMG, drag Academic OS to Applications. The app is not signed with an Apple certificate yet, so the first launch needs one extra step: double-click, dismiss the warning, then System Settings, Privacy & Security, "Open Anyway".

**Windows:** download the zip, extract it, run `academic-os.exe`. If SmartScreen objects, click "More info" then "Run anyway".

**Linux / Chromebook (Crostini):** download the tarball, extract, run `academic-os`.

Upgrading: install the new version over the old one. Your data is kept.

## Local AI

Chat, essay feedback, and the assistants need a language model. Open Settings, Local AI, and download one (2.5 GB recommended, 400 MB for older machines). After that everything works offline. If you already run [Ollama](https://ollama.com), the app uses it instead.

## Running from source

Backend (Python 3.14):

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
ACADEMIC_OS_DATA=~/.academic-os .venv/bin/uvicorn backend.app:app --port 7878
```

Frontend (Node, npm):

```
cd webui
npm install
npm run dev
```

Tests: `.venv/bin/python -m pytest tests/ -q`

## Your data

Everything is plain files under `~/.academic-os`: JSONL ledgers, markdown notes, and your attached documents. Point the in-app backup at any folder (a cloud-synced one works; credentials are excluded from backups). Restore is one click and takes a safety snapshot first.
