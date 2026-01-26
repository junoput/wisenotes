from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.schemas import NoteCreate, NoteDocument, NoteUpdate
from app.services.notes import NoteService
from app.web.dependencies import get_note_service
from app.config import get_settings

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/api")


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration"""
    return {"status": "ok"}


@router.get("/notes")
async def list_notes(service: NoteService = Depends(get_note_service)):
    return service.list_notes()


@router.get("/notes/{note_id}")
async def get_note(note_id: str, service: NoteService = Depends(get_note_service)):
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.post("/notes")
async def create_note(payload: NoteCreate, service: NoteService = Depends(get_note_service)):
    return service.create_note(payload)


@router.put("/notes/{note_id}")
async def update_note(
    note_id: str, payload: NoteUpdate, service: NoteService = Depends(get_note_service)
):
    note = service.update_note(note_id, payload)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, service: NoteService = Depends(get_note_service)):
    ok = service.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    return JSONResponse({"status": "deleted"})


@router.get("/export")
async def export_notes(service: NoteService = Depends(get_note_service)):
    return service.export_document()


@router.post("/import")
async def import_notes(
    request: Request, file: UploadFile, service: NoteService = Depends(get_note_service)
):
    settings = get_settings()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > settings.max_payload_bytes:
        raise HTTPException(status_code=413, detail="Import too large")
    try:
        doc = NoteDocument.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON document") from exc
    imported = service.import_document(doc)
    notes = service.list_notes()
    active = notes[0] if notes else None
    return templates.TemplateResponse(
        "partials/note_list.html", {"request": request, "notes": notes, "active": active}
    )


@router.post("/notes/{note_id}/media/upload")
async def upload_media(
    note_id: str, file: UploadFile, service: NoteService = Depends(get_note_service)
):
    """Upload media file to note's media folder."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    settings = get_settings()
    content = await file.read()
    
    # Max 10MB per file
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    
    # Save to media folder
    relative_path = service.repo.save_media(note.name, file.filename, content)
    
    return JSONResponse({
        "filename": file.filename,
        "path": relative_path
    })


@router.get("/notes/{note_id}/media/list")
async def list_media(note_id: str, service: NoteService = Depends(get_note_service)):
    """List all media files in a note's media folder."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    files = service.repo.list_media(note.name)
    return JSONResponse({"media": files})


@router.delete("/notes/{note_id}/media/{filename}")
async def delete_media(
    note_id: str, filename: str, service: NoteService = Depends(get_note_service)
):
    """Delete a media file."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    ok = service.repo.delete_media(note.name, filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    return JSONResponse({"status": "deleted"})


@router.get("/notes/{note_id}/media/{filename}")
async def get_media(
    note_id: str, filename: str, service: NoteService = Depends(get_note_service)
):
    """Serve a media file."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    filepath = service.repo.get_media_path(note.name, filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    return FileResponse(filepath)

