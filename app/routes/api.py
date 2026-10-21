from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.assets import ASSET_VERSION
from app.media_urls import media_kind
from app.media_urls import missing_name
from app.schemas import NoteCreate
from app.schemas import NoteUpdate
from app.services.bundle import BundleError
from app.services.bundle import export_zip
from app.services.bundle import import_bundle
from app.services.image_processing import STORED_MEDIA_TYPES
from app.services.notes import NoteService
from app.services.notes import get_note_service

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.filters["media_kind"] = media_kind
templates.env.filters["missing_name"] = missing_name

router = APIRouter(prefix="/api")


@router.get("/notes")
async def list_notes(service: NoteService = Depends(get_note_service)):
    return service.list_notes()


@router.get("/notes/{note_id}")
async def get_note(note_id: str, service: NoteService = Depends(get_note_service)):
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def _refused_detail(refused: list[str]) -> str:
    return (
        "Media blocks refused (an image of ours that does not exist, or a "
        f"data: URL that is not PNG, JPEG, WebP or GIF): {'; '.join(refused)}"
    )


@router.post("/notes")
async def create_note(payload: NoteCreate, service: NoteService = Depends(get_note_service)):
    note, refused = service.create_note_checked(payload)
    if refused:
        raise HTTPException(status_code=409, detail=_refused_detail(refused))
    return note


@router.put("/notes/{note_id}")
async def update_note(
    note_id: str, payload: NoteUpdate, service: NoteService = Depends(get_note_service)
):
    note, gone = service.update_note_checked(note_id, payload)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if gone:
        # A block would request a file that is not there (20261021-016).
        raise HTTPException(
            status_code=409,
            detail=_refused_detail(gone),
        )
    return note


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, service: NoteService = Depends(get_note_service)):
    note, borrowers, _ = service.delete_note_unless_shown(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if borrowers:
        # Same refusal as the page route: the note's folder holds images these show.
        raise HTTPException(
            status_code=409,
            detail=f"Other notes show images from this note: {'; '.join(borrowers)}",
        )
    return JSONResponse({"status": "deleted"})


@router.get("/export")
async def export_notes(service: NoteService = Depends(get_note_service)):
    return service.export_document()


@router.post("/import")
async def import_notes(
    request: Request, file: UploadFile, service: NoteService = Depends(get_note_service)
):
    """Create notes from an export .json or a bundle .zip; same sanitisation as the page route."""
    content = await file.read()
    try:
        result = await run_in_threadpool(import_bundle, service, file.filename or "", content)
    except BundleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if request.headers.get("hx-request", "").lower() == "true":
        notes = service.list_notes()
        return templates.TemplateResponse(
            request,
            "partials/hx_refresh.html",
            {
                "request": request,
                "notes": notes,
                "active": result.notes[0] if result.notes else None,
            },
        )
    return JSONResponse(
        {
            "imported": [n.id for n in result.notes],
            "images": result.images,
            "skipped": result.skipped,
            "missing": result.missing,
        }
    )


@router.get("/export.zip")
async def export_all_zip(service: NoteService = Depends(get_note_service)):
    return Response(
        export_zip(service),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="wisenotes.zip"'},
    )


@router.get("/notes/{note_id}/media/list")
async def list_media(note_id: str, service: NoteService = Depends(get_note_service)):
    """List all media files in a note's media folder."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    files = service.repo.list_media(note.name)
    return JSONResponse({"media": files})


@router.get("/notes/{note_id}/media/{filename}")
async def get_media(note_id: str, filename: str, service: NoteService = Depends(get_note_service)):
    """Serve a media file."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    filepath = service.repo.get_media_path(note.name, filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="Media file not found")

    # Only the two types the pipeline stores are served as images. Anything else on
    # disk (older uploads, hand-copied files) is offered as a download, never rendered.
    media_type = STORED_MEDIA_TYPES.get(filepath.suffix.lower())
    if media_type is None:
        return FileResponse(
            filepath,
            media_type="application/octet-stream",
            filename=filepath.name,  # Starlette encodes it per RFC 6266, non-ASCII included
        )
    return FileResponse(filepath, media_type=media_type)
