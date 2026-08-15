"""Connector endpoints — LMS calendar-feed (ICS) sync."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

_ics_service = None
_canvas_service = None
_courses_service = None


def get_ics_service():
    global _ics_service
    if _ics_service is None:
        from backend.services.ics_sync import IcsSyncService
        from backend.vault import agentic_os_dir
        _ics_service = IcsSyncService(data_dir=agentic_os_dir() / "data" / "connectors")
    return _ics_service


def get_canvas_service():
    global _canvas_service
    if _canvas_service is None:
        from backend.services.canvas_sync import CanvasSyncService
        from backend.vault import agentic_os_dir
        _canvas_service = CanvasSyncService(data_dir=agentic_os_dir() / "data" / "connectors")
    return _canvas_service


def get_courses_service():
    global _courses_service
    if _courses_service is None:
        from backend.services.courses import CoursesService
        from backend.vault import agentic_os_dir
        _courses_service = CoursesService(data_dir=agentic_os_dir() / "data" / "courses")
    return _courses_service


def reset_services() -> None:  # for tests
    global _ics_service, _canvas_service, _courses_service
    _ics_service = None
    _canvas_service = None
    _courses_service = None


class FeedBody(BaseModel):
    url: HttpUrl


class FeedRemoveBody(BaseModel):
    id: int


@router.get("/ics")
def ics_status() -> dict:
    """Feeds + last sync result. Feed URLs carry a per-student secret token,
    so this returns each feed's id + host only, never the full URL."""
    return get_ics_service().masked_config()


@router.post("/ics")
def ics_add_feed(body: FeedBody) -> dict:
    """Register a calendar-feed URL (Canvas/Moodle/Brightspace 'calendar feed')."""
    get_ics_service().add_feed(str(body.url))
    return get_ics_service().masked_config()


@router.post("/ics/remove")
def ics_remove_feed(body: FeedRemoveBody) -> dict:
    """Unregister a feed by id (from GET /ics's masked list) — the full feed
    URL never has to round-trip back from the client. Already-synced
    assignments stay (they're the student's data now)."""
    svc = get_ics_service()
    svc.remove_feed_by_id(body.id)
    # Return the MASKED config — the raw remove result carries the remaining
    # feeds' full URLs incl. their secret tokens (same leak the add/get paths
    # already avoid via masked_config()).
    return svc.masked_config()


@router.post("/ics/sync")
async def ics_sync() -> JSONResponse:
    """Fetch all feeds now and upsert assignments."""
    cfg = get_ics_service().config()
    if not cfg["feeds"]:
        return JSONResponse({"error": "no_feeds", "detail": "add a feed URL first"},
                            status_code=400)
    result = await get_ics_service().sync(get_courses_service())
    return JSONResponse(result)


class CanvasCredsBody(BaseModel):
    base_url: HttpUrl
    token: str


@router.get("/canvas")
def canvas_status() -> dict:
    """Connection state (token masked) + last sync result."""
    return get_canvas_service().masked_config()


@router.post("/canvas")
async def canvas_set(body: CanvasCredsBody) -> dict:
    """Save the school's Canvas base URL + the student's personal token, then
    kick off an immediate background sync — the student sees their courses
    without needing to find "Sync now"."""
    token = body.token.strip()
    if len(token) < 8:
        return JSONResponse({"error": "bad_token", "detail": "token looks too short"},
                            status_code=422)
    result = get_canvas_service().set_credentials(str(body.base_url), token)
    if result.get("connected"):
        asyncio.create_task(get_canvas_service().sync(get_courses_service()))
    return result


@router.post("/canvas/clear")
def canvas_clear() -> dict:
    """Forget the stored credentials. Synced data stays."""
    return get_canvas_service().clear_credentials()


@router.post("/canvas/sync")
async def canvas_sync() -> JSONResponse:
    """Pull active courses + assignments from Canvas now. On a total failure
    (bad token, unreachable school, Canvas outage) responds non-2xx with an
    {error: "auth_error" | "network_error" | "canvas_error", ...} body so the
    UI can show a specific message instead of a generic failure."""
    masked = get_canvas_service().masked_config()
    if not masked["connected"]:
        return JSONResponse({"error": "not_connected",
                             "detail": "set base_url and token first"}, status_code=400)
    result = await get_canvas_service().sync(get_courses_service())
    kind = result.get("error_kind")
    if kind:
        detail = result["errors"][0]["error"] if result.get("errors") else kind
        body = {**result, "error": kind, "detail": detail}
        if result.get("error_status") is not None:
            body["status"] = result["error_status"]
        return JSONResponse(body, status_code=502)
    return JSONResponse(result)
