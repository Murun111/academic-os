"""Delegate a real coding task to a CLI coding agent (claude or codex).

Spawns the agent in the background so the approval endpoint returns
immediately.  Best-effort vault summary + macOS notification on completion.
Never raises to the caller.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from asyncio.subprocess import PIPE
from pathlib import Path

PROJECTS_ROOT: Path = Path.home() / "Code" / "agentic-os-projects"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _slug(name: str) -> str:
    """Return a safe folder name from an arbitrary project name."""
    return _SLUG_RE.sub("_", name).strip("_") or "project"


def _augmented_path() -> str:
    """PATH that includes ~/.local/bin and other dirs where claude/codex live."""
    extra = [
        str(Path.home() / ".local/bin"),
        str(Path.home() / "bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    p = os.environ.get("PATH", "")
    return ":".join(extra) + ":" + p


def _argv_for(backend: str, prompt: str) -> list[str]:
    """CLI invocation for a coding agent run (writes files in cwd)."""
    if backend == "codex":
        return ["codex", "exec", "--full-auto", prompt]
    if backend == "gemini":
        # Gemini's huge-context reviewer. --yolo auto-approves edits (parity
        # with the other agents' auto-edit modes). Needs GEMINI_API_KEY — the
        # free individual tier was retired (IneligibleTierError).
        return ["gemini", "-p", prompt, "-m", "gemini-2.5-pro", "--yolo"]
    return ["claude", "-p", prompt, "--permission-mode", "acceptEdits"]


def _review_prompt(task: str) -> str:
    return (
        "Review the existing code in this project directory for bugs, missing "
        "functionality, security issues, and quality problems, then FIX them by "
        "editing the files directly — do NOT rewrite from scratch. "
        f"The project was built to this spec: {task}"
    )


async def run_code_task(
    task: str, project: str, backend: str = "claude", mode: str = "solo"
) -> dict:
    """Delegate *task* to a CLI coding agent writing into PROJECTS_ROOT/<project>.

    mode="solo"   → one agent (`backend`) builds it.
    mode="collab" → claude BUILDS, then codex REVIEWS + FIXES the same folder
                    (cross-model review catches what the author missed).
    mode="panel"  → claude BUILDS → codex REVIEWS → gemini REVIEWS (a third
                    pair of eyes; the PDF's full Claude→Codex→Gemini pipeline).
                    Stages whose CLI is unavailable simply fail that step.

    Returns immediately; real work runs in a background asyncio Task.
    """
    if backend not in {"claude", "codex"}:
        backend = "claude"
    if mode not in {"solo", "collab", "panel"}:
        mode = "solo"

    try:
        slug = _slug(project)
        proj_dir = PROJECTS_ROOT / slug
        proj_dir.mkdir(parents=True, exist_ok=True)

        if mode == "collab":
            steps = [("claude", task), ("codex", _review_prompt(task))]
        elif mode == "panel":
            steps = [("claude", task), ("codex", _review_prompt(task)),
                     ("gemini", _review_prompt(task))]
        else:
            steps = [(backend, task)]

        async def _build() -> None:
            try:
                env = {**os.environ, "PATH": _augmented_path()}
                rcs: list[int] = []
                for step_backend, prompt in steps:
                    argv = _argv_for(step_backend, prompt)
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            *argv, cwd=str(proj_dir), stdout=PIPE, stderr=PIPE, env=env
                        )
                        try:
                            await asyncio.wait_for(proc.communicate(), timeout=1200)
                            rcs.append(proc.returncode or 0)
                        except asyncio.TimeoutError:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            rcs.append(-1)
                    except Exception:
                        rcs.append(-2)
                rc = rcs[-1] if rcs else -2

                # Collect up to 50 relative file paths under proj_dir
                files: list[str] = []
                for root, _, fnames in os.walk(str(proj_dir)):
                    for fname in fnames:
                        rel = os.path.relpath(
                            os.path.join(root, fname), str(proj_dir)
                        )
                        files.append(rel)
                        if len(files) >= 50:
                            break
                    if len(files) >= 50:
                        break
                n = len(files)
                pipeline = " → ".join(b for b, _ in steps)  # e.g. "claude → codex"

                # Vault summary — best-effort
                try:
                    from backend.services.tools import vault_write
                    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    file_list = "\n".join(f"- {f}" for f in files)
                    content = (
                        f"---\nlast_updated: {ts}\n---\n\n"
                        f"# code.task: {project}\n\n"
                        f"**task:** {task}\n\n"
                        f"**mode:** {mode}  ·  **pipeline:** {pipeline}\n\n"
                        f"**return_codes:** {rcs}\n\n"
                        f"## Files ({n})\n\n{file_list}\n"
                    )
                    await vault_write(f"output/code/{slug}.md", content)
                except Exception:
                    pass

                # Notification + event — best-effort
                try:
                    from backend.services import notify, events
                    notify.notify(
                        f"✓ code: {project}",
                        f"{pipeline} finished — {n} files in {proj_dir.name}",
                    )
                    events.publish({
                        "type": "code",
                        "phase": "done",
                        "project": project,
                        "dir": str(proj_dir),
                        "pipeline": pipeline,
                        "mode": mode,
                        "files": n,
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
                except Exception:
                    pass

            except Exception:
                pass

        asyncio.create_task(_build())

        return {
            "ok": True,
            "status": "building",
            "project": project,
            "dir": str(proj_dir),
            "mode": mode,
            "pipeline": " → ".join(b for b, _ in steps),
            "note": (
                "coding started in the background; "
                "you'll get a notification when it's done"
            ),
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
