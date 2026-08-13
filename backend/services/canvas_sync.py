"""Canvas REST connector — the rich LMS sync.

A student self-generates a personal access token in Canvas
(Account → Settings → New Access Token) and pastes it plus their school's
Canvas base URL. The sync pulls active courses and their assignments
(with submission state and score) and upserts them into the Courses module.

Policies, same spirit as ICS sync:
- upsert by external_id (canvas-<id>) — re-sync updates, never duplicates
- student data is never clobbered: status only promotes todo→done (when
  Canvas says submitted/graded), never demotes; a manually entered grade
  is never overwritten
- per-course failures are reported, not raised

The token lives only in data/connectors/canvas.json in the local data root.
It is never logged and the status endpoint masks it.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx


def _classify_error(exc: Exception) -> str:
    """Map a sync-time exception to a stable code the UI can show a
    friendly message for: auth_error (bad/expired token), network_error
    (couldn't reach Canvas at all), canvas_error (Canvas responded with
    some other problem)."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            return "auth_error"
        return "canvas_error"
    if isinstance(exc, httpx.TransportError):  # connect/timeout/DNS/etc.
        return "network_error"
    return "canvas_error"


def _error_status(exc: Exception) -> int | None:
    """Canvas's own HTTP status, when the exception carries one — lets the UI
    show "Canvas had a problem (HTTP 500)" instead of a bare message."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


SYNC_TIMEOUT_SECONDS = 120


def _iso_date(dt: str | None) -> str | None:
    """Canvas due_at '2026-09-15T23:59:00Z' → '2026-09-15'."""
    if not dt:
        return None
    return dt[:10] if len(dt) >= 10 else None


class CanvasSyncService:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "canvas.json"

    # config -------------------------------------------------------
    def config(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"base_url": "", "token": "", "last_sync": None, "last_result": None}

    def _save(self, cfg: dict) -> None:
        """Write atomically: tmp file in the same dir, then replace — avoids a
        half-written canvas.json if the process dies mid-write."""
        tmp = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        os.replace(tmp, self._path)

    def set_credentials(self, base_url: str, token: str) -> dict:
        cfg = self.config()
        cfg["base_url"] = base_url.rstrip("/")
        cfg["token"] = token.strip()
        self._save(cfg)
        return self.masked_config()

    def clear_credentials(self) -> dict:
        cfg = self.config()
        cfg["base_url"] = ""
        cfg["token"] = ""
        self._save(cfg)
        return self.masked_config()

    def masked_config(self) -> dict:
        """Config safe to return to the UI — token value never leaves disk."""
        cfg = self.config()
        token = cfg.get("token") or ""
        return {
            "base_url": cfg.get("base_url") or "",
            "connected": bool(token and cfg.get("base_url")),
            "token_hint": f"…{token[-4:]}" if token else "",
            "last_sync": cfg.get("last_sync"),
            "last_result": cfg.get("last_result"),
        }

    # sync ---------------------------------------------------------
    async def sync(self, courses_service) -> dict:
        """Public entry point: runs the real sync under an overall deadline so
        a hung Canvas connection can't wedge the app forever. Per-request
        timeouts (below) usually fire first; this is the backstop."""
        try:
            return await asyncio.wait_for(
                self._sync_impl(courses_service), timeout=SYNC_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            cfg = self.config()
            result: dict = {
                "courses": 0, "created": 0, "updated": 0, "unchanged": 0,
                "errors": [{"scope": "sync",
                            "error": f"sync timed out after {SYNC_TIMEOUT_SECONDS}s",
                            "kind": "network_error"}],
                "error_kind": "network_error",
            }
            return self._finish(cfg, result)

    async def _sync_impl(self, courses_service) -> dict:
        cfg = self.config()
        base, token = cfg.get("base_url") or "", cfg.get("token") or ""
        result: dict = {"courses": 0, "created": 0, "updated": 0, "unchanged": 0, "errors": []}
        if not base or not token:
            result["errors"].append({"scope": "config", "error": "base_url and token required",
                                      "kind": "config_error"})
            result["error_kind"] = "config_error"
            return result

        headers = {"Authorization": f"Bearer {token}"}
        existing_courses = {c.external_id: c for c in courses_service.list_courses() if c.external_id}
        existing_assignments = {a.external_id: a for a in courses_service.list_assignments() if a.external_id}

        async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=True) as client:
            try:
                r = await client.get(f"{base}/api/v1/courses",
                                     params={"enrollment_state": "active", "per_page": 50,
                                             "include[]": "total_scores"})
                r.raise_for_status()
                canvas_courses = r.json()
            except Exception as e:
                kind = _classify_error(e)
                status = _error_status(e)
                err: dict = {"scope": "courses", "error": f"{type(e).__name__}: {e}", "kind": kind}
                if status is not None:
                    err["status"] = status
                result["errors"].append(err)
                result["error_kind"] = kind
                if status is not None:
                    result["error_status"] = status
                return self._finish(cfg, result)

            for cc in canvas_courses:
                cid = cc.get("id")
                cname = (cc.get("name") or cc.get("course_code") or "").strip()
                if not cid or not cname:
                    continue
                result["courses"] += 1
                ext = f"canvas-{cid}"
                if ext in existing_courses:
                    course = existing_courses[ext]
                else:
                    term = ((cc.get("term") or {}).get("name") or "Canvas").strip() or "Canvas"
                    course = courses_service.add_course(
                        name=cname, term=term, source="canvas", external_id=ext)
                    existing_courses[ext] = course

                # course total from enrollments (include[]=total_scores) —
                # Canvas-owned, so always refresh it
                score = None
                for enr in cc.get("enrollments") or []:
                    s = enr.get("computed_current_score")
                    if isinstance(s, (int, float)):
                        score = round(float(s), 1)
                        break
                if score is not None and course.canvas_score != score:
                    try:
                        courses_service.set_canvas_score(course.id, score)
                    except Exception as e:  # never fail the whole sync on one grade
                        result["errors"].append({"scope": cname, "error": f"grade: {e}",
                                                  "kind": _classify_error(e)})

                try:
                    ra = await client.get(
                        f"{base}/api/v1/courses/{cid}/assignments",
                        params={"per_page": 50, "include[]": "submission"})
                    ra.raise_for_status()
                    assignments = ra.json()
                except Exception as e:
                    result["errors"].append({"scope": cname, "error": f"{type(e).__name__}: {e}",
                                              "kind": _classify_error(e)})
                    continue

                for aa in assignments:
                    aid = aa.get("id")
                    title = (aa.get("name") or "").strip()
                    if not aid or not title:
                        continue
                    ext_a = f"canvas-a-{aid}"
                    due = _iso_date(aa.get("due_at"))
                    sub = aa.get("submission") or {}
                    submitted = sub.get("workflow_state") in ("submitted", "graded")
                    score = sub.get("score")
                    points = aa.get("points_possible")
                    pct = None
                    if (sub.get("workflow_state") == "graded" and
                            isinstance(score, (int, float)) and
                            isinstance(points, (int, float)) and points > 0):
                        pct = round(score / points * 100, 1)

                    prev = existing_assignments.get(ext_a)
                    if prev is None:
                        courses_service.add_assignment(
                            course_id=course.id, title=title, due=due,
                            status="done" if submitted else "todo",
                            grade=pct, source="canvas", external_id=ext_a)
                        result["created"] += 1
                    else:
                        fields = {}
                        if prev.title != title:
                            fields["title"] = title
                        if prev.due != due:
                            fields["due"] = due
                        # promote only — never revert a student's "done"
                        if submitted and prev.status != "done":
                            fields["status"] = "done"
                        # fill grade only if the student hasn't entered one
                        if pct is not None and prev.grade is None:
                            fields["grade"] = pct
                        if fields:
                            courses_service.update_assignment(prev.id, **fields)
                            result["updated"] += 1
                        else:
                            result["unchanged"] += 1

        return self._finish(cfg, result)

    def _finish(self, cfg: dict, result: dict) -> dict:
        cfg["last_sync"] = datetime.now(timezone.utc).isoformat()
        cfg["last_result"] = result
        self._save(cfg)
        return result


AUTO_SYNC_INTERVAL_SECONDS = 6 * 60 * 60


async def auto_sync_loop() -> None:
    """Background task: while the app runs and Canvas is connected, resync every
    6 hours so assignments and grades stay fresh without any clicking."""
    await asyncio.sleep(60)  # let the app boot; first sync a minute in
    while True:
        try:
            from backend.routers.connectors import get_canvas_service, get_courses_service
            canvas = get_canvas_service()
            if canvas.config().get("token"):
                result = await canvas.sync(get_courses_service())
                print(f"[canvas] auto-sync: {result['courses']} courses, "
                      f"{result['created']} new, {result['updated']} updated, "
                      f"{len(result['errors'])} errors")
        except Exception as e:  # noqa: BLE001 — the loop must survive anything
            print(f"[canvas] auto-sync failed: {e!r}")
        await asyncio.sleep(AUTO_SYNC_INTERVAL_SECONDS)
