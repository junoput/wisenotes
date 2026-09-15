"""HTML routes.

Every page works without JavaScript; htmx enhances it. Two conventions make that
hold: a mutating POST answers a plain browser with a redirect to the page
(Post/Redirect/Get) and an htmx request with the out-of-band fragment, and every
element carrying an hx-* attribute is also a real <form action method> or
<a href>.
"""

import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.blocks import get_all_blocks
from app.schemas import Chapter
from app.schemas import Note
from app.schemas import NoteCreate
from app.schemas import NoteUpdate
from app.services.image_processing import process_uploaded_image
from app.services.notes import NoteService
from app.services.notes import get_note_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request", "").lower() == "true"


def _ctx(request: Request, **kwargs) -> dict:
    ctx = {"request": request, "block_types": get_all_blocks(), "editing": None, "settings": False}
    ctx.update(kwargs)
    return ctx


def _page(request: Request, service: NoteService, note: Note | None, **extra) -> Response:
    """Full page, or the out-of-band fragment for htmx."""
    template = "partials/hx_refresh.html" if _is_htmx(request) else "index.html"
    return templates.TemplateResponse(
        request, template, _ctx(request, notes=service.list_notes(), active=note, **extra)
    )


def _after_change(
    request: Request, service: NoteService, note: Note | None, headers: dict | None = None
) -> Response:
    """Answer a mutating POST: fragment for htmx, 303 to the page otherwise."""
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/hx_refresh.html",
            _ctx(request, notes=service.list_notes(), active=note),
            headers=headers,
        )
    return RedirectResponse(url=f"/notes/{note.id}" if note else "/", status_code=303)


def _note_or_404(service: NoteService, note_id: str) -> Note:
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def _chapter_or_404(note: Note, chapter_id: str) -> Chapter:
    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


def _normalize_source(value: str | None) -> str | None:
    """'a; b ;; c' -> 'a; b; c'; empty -> None."""
    parts = [p.strip() for p in (value or "").split(";")]
    parts = [p for p in parts if p]
    return "; ".join(parts) if parts else None


# ---------------------------------------------------------------- notes


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, service: NoteService = Depends(get_note_service)):
    return _page(request, service, None)


@router.post("/notes")
async def create_note(
    request: Request,
    title: str = Form("Untitled note"),
    service: NoteService = Depends(get_note_service),
):
    note = service.create_note(NoteCreate(title=title))
    note = service.add_chapter(note.id, title="Chapter 1") or note
    return _after_change(request, service, note)


@router.get("/notes/{note_id}", response_class=HTMLResponse)
async def fetch_note(
    note_id: str, request: Request, service: NoteService = Depends(get_note_service)
):
    return _page(request, service, _note_or_404(service, note_id))


@router.get("/notes/{note_id}/settings", response_class=HTMLResponse)
async def note_settings(
    note_id: str, request: Request, service: NoteService = Depends(get_note_service)
):
    note = _note_or_404(service, note_id)
    folders = sorted({n.folder for n in service.list_notes() if n.folder})
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/note_settings.html",
            _ctx(request, note=note, existing_folders=folders),
        )
    return _page(request, service, note, settings=True, existing_folders=folders)


@router.post("/notes/{note_id}/title")
async def update_note_title(
    note_id: str,
    request: Request,
    title: str = Form(...),
    service: NoteService = Depends(get_note_service),
):
    note = service.update_note(note_id, NoteUpdate(title=title))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


@router.post("/notes/{note_id}/folder")
async def update_note_folder(
    note_id: str,
    request: Request,
    folder: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    note = service.update_note(note_id, NoteUpdate(folder=folder.strip() or None))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


@router.post("/notes/{note_id}/delete")
async def delete_note(
    note_id: str, request: Request, service: NoteService = Depends(get_note_service)
):
    if not service.delete_note(note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return _after_change(
        request, service, notes[0] if notes else None, headers={"HX-Trigger": "close-note-settings"}
    )


# ---------------------------------------------------------------- blocks


@router.post("/notes/{note_id}/chapters")
async def add_block(
    note_id: str,
    request: Request,
    block_type: str = Form("chapter"),
    position: str = Form("end"),
    ref_id: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    """position: end (root), after/before (sibling of ref_id), child (last child of ref_id)."""
    if position == "after":
        note = service.add_chapter_after(note_id, prev_id=ref_id, block_type=block_type)
    elif position == "before":
        note = service.add_chapter_before(note_id, next_id=ref_id, block_type=block_type)
    elif position == "child":
        note = service.add_chapter_child(note_id, parent_id=ref_id, block_type=block_type)
    else:
        note = service.add_chapter(note_id, block_type=block_type)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


@router.get("/notes/{note_id}/chapters/{chapter_id}/edit", response_class=HTMLResponse)
async def edit_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    note = _note_or_404(service, note_id)
    chapter = _chapter_or_404(note, chapter_id)
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/chapter_edit_form.html",
            _ctx(
                request, note=note, chapter=chapter, media_files=service.repo.list_media(note.name)
            ),
        )
    return _page(
        request, service, note, editing=chapter, media_files=service.repo.list_media(note.name)
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/edit")
async def update_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    title: str = Form(""),
    content_text: str = Form(""),
    language: str = Form(""),
    source: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    note = service.update_chapter(
        note_id, chapter_id, title, content_text, language or None, _normalize_source(source)
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


@router.post("/notes/{note_id}/chapters/{chapter_id}/delete")
async def delete_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    note = service.delete_chapter(note_id, chapter_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


@router.post("/notes/{note_id}/chapters/{chapter_id}/reorder")
async def reorder_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    op: str = Form(...),
    service: NoteService = Depends(get_note_service),
):
    ops = {
        "up": service.move_chapter_up,
        "down": service.move_chapter_down,
        "indent": service.indent_chapter,
        "outdent": service.outdent_chapter,
    }
    if op not in ops:
        raise HTTPException(status_code=400, detail="op must be up, down, indent or outdent")
    note = ops[op](note_id, chapter_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


@router.post("/notes/{note_id}/chapters/{chapter_id}/move")
async def move_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    target_id: str = Form(""),
    parent_id: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    """Drag-and-drop target (drag-drop.js); the buttons use /reorder."""
    try:
        note = service.move_chapter(note_id, chapter_id, target_id, parent_id or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _after_change(request, service, note)


# ---------------------------------------------------------------- media


def _media_reply(request: Request, service: NoteService, note: Note, chapter_id: str) -> Response:
    """Gallery fragment for htmx; back to the block's edit page otherwise."""
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/media_gallery.html",
            _ctx(
                request,
                active=note,
                chapter_id=chapter_id,
                media_files=service.repo.list_media(note.name),
            ),
        )
    return RedirectResponse(url=f"/notes/{note.id}/chapters/{chapter_id}/edit", status_code=303)


@router.post("/notes/{note_id}/media/upload")
async def upload_media(
    note_id: str,
    request: Request,
    file: UploadFile,
    chapter_id: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    note = _note_or_404(service, note_id)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    try:
        new_filename, processed, metadata = process_uploaded_image(
            file.filename or "upload", content
        )
    except Exception as e:  # Pillow raises several types for a bad file
        raise HTTPException(status_code=400, detail="Not a readable image") from e
    service.save_media_file(note_id, new_filename, processed)
    service.save_module_metadata(note_id, "media", new_filename, metadata.to_dict())
    return _media_reply(request, service, note, chapter_id)


@router.post("/notes/{note_id}/media/{filename}/delete")
async def delete_media(
    note_id: str,
    filename: str,
    request: Request,
    chapter_id: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    note = _note_or_404(service, note_id)
    if not service.repo.delete_media(note.name, filename):
        raise HTTPException(status_code=404, detail="Media file not found")
    return _media_reply(request, service, note, chapter_id)


@router.post("/notes/{note_id}/chapters/{chapter_id}/media/select")
async def select_media(
    note_id: str,
    chapter_id: str,
    request: Request,
    url: str = Form(...),
    service: NoteService = Depends(get_note_service),
):
    note = _note_or_404(service, note_id)
    chapter = _chapter_or_404(note, chapter_id)
    note = service.update_chapter(
        note_id, chapter_id, chapter.title, url, chapter.language, chapter.source
    )
    return _after_change(request, service, note)


# ---------------------------------------------------------------- pretty URLs (must stay last)


@router.get("/{note_name}", response_class=HTMLResponse)
async def fetch_note_by_name(
    note_name: str, request: Request, service: NoteService = Depends(get_note_service)
):
    note = next((n for n in service.list_notes() if n.name == note_name), None)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _page(request, service, note)
