"""Documents Hub router — /api/documents/*."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.documents import DocumentsService, KINDS, STATUSES

router = APIRouter(prefix="/api/documents", tags=["documents"])

_service: DocumentsService | None = None


def get_service() -> DocumentsService:
    global _service
    if _service is None:
        from backend.vault import agentic_os_dir

        _service = DocumentsService(data_dir=agentic_os_dir() / "data" / "documents")
    return _service


def reset_service() -> None:  # for tests
    global _service
    _service = None


DocKind = Literal["essay", "cv", "transcript", "lor", "certificate", "other"]
DocStatus = Literal["draft", "in_review", "final"]


class _AddBody(BaseModel):
    title: str = Field(..., min_length=1)
    kind: DocKind
    status: DocStatus = "draft"
    tags: list[str] = Field(default_factory=list)
    linked_application_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class _UpdateBody(BaseModel):
    title: Optional[str] = None
    kind: Optional[DocKind] = None
    status: Optional[DocStatus] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    content: Optional[str] = None


class _VersionBody(BaseModel):
    note: str = Field(..., min_length=1)


class _LinkBody(BaseModel):
    application_id: str = Field(..., min_length=1)


@router.get("")
def list_documents(
    kind: Optional[str] = Query(None, description=f"one of: {', '.join(KINDS)}"),
    tag: Optional[str] = Query(None),
    application_id: Optional[str] = Query(None),
) -> dict:
    items = get_service().list_all(kind=kind, tag=tag, application_id=application_id)
    return {"items": [i.to_dict() for i in items], "count": len(items)}


@router.post("")
def add_document(body: _AddBody) -> dict:
    item = get_service().add(
        title=body.title,
        kind=body.kind,
        status=body.status,
        tags=body.tags,
        linked_application_ids=body.linked_application_ids,
        notes=body.notes,
    )
    return {"ok": True, "item": item.to_dict()}


@router.get("/{doc_id}")
def get_document(doc_id: str) -> dict:
    try:
        item = get_service().get(doc_id)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": doc_id}, status_code=404)
    return {"item": item.to_dict()}


@router.patch("/{doc_id}")
def update_document(doc_id: str, body: _UpdateBody) -> dict:
    try:
        item = get_service().update(
            doc_id,
            title=body.title,
            kind=body.kind,
            status=body.status,
            tags=body.tags,
            notes=body.notes,
            content=body.content,
        )
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": doc_id}, status_code=404)
    return {"ok": True, "item": item.to_dict()}


@router.delete("/{doc_id}")
def delete_document(doc_id: str) -> dict:
    try:
        get_service().delete(doc_id)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": doc_id}, status_code=404)
    return {"ok": True}


@router.post("/{doc_id}/versions")
def bump_version(doc_id: str, body: _VersionBody) -> dict:
    try:
        item = get_service().bump_version(doc_id, note=body.note)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": doc_id}, status_code=404)
    return {"ok": True, "item": item.to_dict()}


@router.post("/{doc_id}/link")
def link_document(doc_id: str, body: _LinkBody) -> dict:
    try:
        item = get_service().link(doc_id, application_id=body.application_id)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": doc_id}, status_code=404)
    return {"ok": True, "item": item.to_dict()}


@router.post("/{doc_id}/unlink")
def unlink_document(doc_id: str, body: _LinkBody) -> dict:
    try:
        item = get_service().unlink(doc_id, application_id=body.application_id)
    except KeyError:
        return JSONResponse({"error": "not_found", "detail": doc_id}, status_code=404)
    return {"ok": True, "item": item.to_dict()}
