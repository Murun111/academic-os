"""Applications Pipeline router — /api/applications/*.

Thin FastAPI wrapper over backend.services.applications.ApplicationsService.
Lazily instantiates a module-level singleton pointed at the vault data
root (see backend/vault.py), same pattern as the other wave-2 modules.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.applications import ApplicationsService

router = APIRouter(prefix="/api/applications", tags=["applications"])

_service: ApplicationsService | None = None


def get_service() -> ApplicationsService:
    global _service
    if _service is None:
        from backend.vault import agentic_os_dir

        _service = ApplicationsService(data_dir=agentic_os_dir() / "data" / "applications")
    return _service


def reset_service() -> None:  # for tests
    global _service
    _service = None


# === request bodies ===


class RequirementIn(BaseModel):
    id: Optional[str] = None
    label: str = ""
    done: bool = False


class ApplicationCreate(BaseModel):
    name: str
    type: str
    org: str = ""
    status: Optional[str] = None
    decision_result: Optional[str] = None
    deadline: Optional[str] = None
    url: str = ""
    notes: str = ""
    requirements: Optional[list[RequirementIn]] = None
    document_ids: Optional[list[str]] = None
    amount: Optional[float] = Field(default=None, ge=0)
    app_fee: Optional[float] = Field(default=None, ge=0)
    fee_waived: bool = False


class ApplicationUpdate(BaseModel):
    name: Optional[str] = None
    org: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    decision_result: Optional[str] = None
    deadline: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    requirements: Optional[list[RequirementIn]] = None
    document_ids: Optional[list[str]] = None
    amount: Optional[float] = Field(default=None, ge=0)
    app_fee: Optional[float] = Field(default=None, ge=0)
    fee_waived: Optional[bool] = None
    archived: Optional[bool] = None


class RequirementCreate(BaseModel):
    label: str


class RequirementUpdate(BaseModel):
    label: Optional[str] = None
    done: Optional[bool] = None


# === routes ===
# NOTE: /deadlines and /costs are registered before /{app_id} so they aren't captured as an id.


@router.get("/deadlines")
def deadlines(days: int = Query(30)) -> dict:
    svc = get_service()
    items = svc.upcoming_deadlines(days=days)
    return {"items": [i.to_dict() for i in items], "count": len(items)}


@router.get("/costs")
def costs() -> dict:
    svc = get_service()
    return svc.costs()


@router.get("")
def list_applications(
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
) -> dict:
    svc = get_service()
    try:
        items = svc.list_all(type=type, status=status)
    except ValueError as e:
        return JSONResponse({"error": "invalid_query", "detail": str(e)}, status_code=422)
    return {"items": [i.to_dict() for i in items], "count": len(items)}


@router.post("")
def create_application(body: ApplicationCreate) -> dict:
    svc = get_service()
    try:
        item = svc.add(
            name=body.name,
            type=body.type,
            org=body.org,
            status=body.status,
            decision_result=body.decision_result,
            deadline=body.deadline,
            url=body.url,
            notes=body.notes,
            requirements=[r.model_dump() for r in body.requirements] if body.requirements else None,
            document_ids=body.document_ids,
            amount=body.amount,
            app_fee=body.app_fee,
            fee_waived=body.fee_waived,
        )
    except ValueError as e:
        return JSONResponse({"error": "invalid_application", "detail": str(e)}, status_code=422)
    return {"ok": True, "item": item.to_dict()}


@router.get("/{app_id}")
def get_application(app_id: str) -> dict:
    svc = get_service()
    try:
        item = svc.get(app_id)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": app_id}, status_code=404)
    return {"item": item.to_dict()}


@router.patch("/{app_id}")
def update_application(app_id: str, body: ApplicationUpdate) -> dict:
    svc = get_service()
    fields = body.model_dump(exclude_unset=True)
    if "requirements" in fields and fields["requirements"] is not None:
        fields["requirements"] = [
            r if isinstance(r, dict) else r.model_dump() for r in fields["requirements"]
        ]
    try:
        item = svc.update(app_id, **fields)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": app_id}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": "invalid_application", "detail": str(e)}, status_code=422)
    return {"ok": True, "item": item.to_dict()}


@router.delete("/{app_id}")
def delete_application(app_id: str) -> dict:
    svc = get_service()
    try:
        svc.delete(app_id)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": app_id}, status_code=404)
    return {"ok": True}


@router.post("/{app_id}/requirements")
def add_requirement(app_id: str, body: RequirementCreate) -> dict:
    svc = get_service()
    try:
        item = svc.add_requirement(app_id, body.label)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": app_id}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": "invalid_requirement", "detail": str(e)}, status_code=422)
    return {"ok": True, "item": item.to_dict()}


@router.patch("/{app_id}/requirements/{req_id}")
def update_requirement(app_id: str, req_id: str, body: RequirementUpdate) -> dict:
    svc = get_service()
    try:
        item = svc.update_requirement(app_id, req_id, label=body.label, done=body.done)
    except KeyError as e:
        detail = req_id if str(e).strip("'\"") == req_id else app_id
        return JSONResponse({"error": "not_found", "detail": detail}, status_code=404)
    return {"ok": True, "item": item.to_dict()}


@router.delete("/{app_id}/requirements/{req_id}")
def delete_requirement(app_id: str, req_id: str) -> dict:
    svc = get_service()
    try:
        item = svc.delete_requirement(app_id, req_id)
    except KeyError as e:
        detail = req_id if str(e).strip("'\"") == req_id else app_id
        return JSONResponse({"error": "not_found", "detail": detail}, status_code=404)
    return {"ok": True, "item": item.to_dict()}
