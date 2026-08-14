"""In-app self-updater endpoints (macOS only, packaged builds only)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.services import updater

router = APIRouter(prefix="/api/update", tags=["update"])

# Same CSRF posture as /ws/events (_WS_ALLOWED_ORIGINS in app.py): browsers
# always send Origin on cross-site POSTs, and a form-POST to localhost is a
# "simple request" that CORSMiddleware alone would NOT block — so a malicious
# webpage could otherwise trigger an install with zero clicks. Absent Origin
# (curl, tests, non-browser clients) stays allowed; only a mismatched browser
# Origin is rejected. Kept as a literal here (not imported from app.py) to
# avoid a circular import — update both lists together.
_ALLOWED_ORIGINS = {
    "http://localhost:7878",
    "http://127.0.0.1:7878",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


@router.get("/status")
def update_status() -> dict:
    """Job state (idle/checking/downloading/verifying/installing/restarting/
    error) plus available/current version info and eligibility, for the
    Settings update button."""
    return updater.status()


@router.post("/install")
def update_install(request: Request) -> JSONResponse:
    """Start the update job in the background. 409 if one is already
    running; 400 with a friendly error if this build isn't eligible."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in _ALLOWED_ORIGINS:
        return JSONResponse({"error": "forbidden_origin"}, status_code=403)
    result = updater.start_install()
    if result.get("ok"):
        return JSONResponse(result, status_code=202)
    if result.get("error") == "already_running":
        return JSONResponse({"error": "already_running"}, status_code=409)
    return JSONResponse(
        {"error_kind": "install_error",
         "message": result.get("message") or "Updates aren't available on this build."},
        status_code=400,
    )
