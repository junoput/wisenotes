"""HTML routes.

Every page works without JavaScript; htmx enhances it. Two conventions make that
hold: a mutating POST answers a plain browser with a redirect to the page
(Post/Redirect/Get) and an htmx request with the out-of-band fragment, and every
element carrying an hx-* attribute is also a real <form action method> or
<a href>.
"""

import logging
from urllib.parse import quote
from urllib.parse import urlsplit

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
from starlette.concurrency import run_in_threadpool

from app.assets import ASSET_VERSION
from app.blocks import get_all_blocks
from app.media_urls import media_kind
from app.media_urls import missing_name
from app.schemas import Chapter
from app.schemas import Note
from app.schemas import NoteCreate
from app.schemas import NoteUpdate
from app.services.bundle import BundleError
from app.services.bundle import export_zip
from app.services.bundle import import_bundle
from app.services.image_processing import UnsupportedImage
from app.services.image_processing import process_uploaded_image
from app.services.notes import NoteNotRemoved
from app.services.notes import NoteService
from app.services.notes import UnreadableNotes
from app.services.notes import get_note_service
from app.services.notes import media_users

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.filters["media_kind"] = media_kind
templates.env.filters["missing_name"] = missing_name
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# htmx appends the add-note and settings overlays to <body>, outside what the
# out-of-band refresh replaces; this event tells app.js to remove them.
CLOSE_OVERLAY = {"HX-Trigger": "close-note-settings"}
THEME_COOKIE_AGE = 400 * 24 * 3600  # the longest browsers keep a cookie


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request", "").lower() == "true"


def _ctx(request: Request, **kwargs) -> dict:
    ctx = {
        "request": request,
        "block_types": get_all_blocks(),
        "editing": None,
        "settings": False,
        "new_note": False,
    }
    ctx.update(kwargs)
    return ctx


def _page(
    request: Request,
    service: NoteService,
    note: Note | None,
    notes: list[Note] | None = None,
    **extra,
) -> Response:
    """Full page, or the out-of-band fragment for htmx. `notes`, when the caller
    already read them, saves reading them again."""
    template = "partials/hx_refresh.html" if _is_htmx(request) else "index.html"
    notes = service.list_notes() if notes is None else notes
    return templates.TemplateResponse(
        request,
        template,
        _ctx(request, notes=notes, active=note, **_disk_notices(service), **extra),
    )


def _disk_notices(service: NoteService) -> dict:
    """What the latest scan of the notes folder could not use, for the notes list.
    Read after list_notes, which sets them."""
    repo = service.repo
    return {
        "unreadable": repo.unreadable,
        "no_note_file": repo.no_note_file,
        "leftovers": repo.leftovers,
    }


def _after_change(
    request: Request, service: NoteService, note: Note | None, headers: dict | None = None
) -> Response:
    """Answer a mutating POST: fragment for htmx, 303 to the page otherwise."""
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/hx_refresh.html",
            _ctx(
                request,
                notes=service.list_notes(),
                active=note,
                **_disk_notices(service),
            ),
            headers=headers,
        )
    return RedirectResponse(url=f"/notes/{note.id}" if note else "/", status_code=303)


def _import_refused(request: Request, service: NoteService, message: str) -> Response:
    """A refused import says why, on the import form: the add-note page without
    scripts, an out-of-band swap into the open overlay with htmx. Both are 400s."""
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/import_error.html",
            {"request": request, "import_error": message, "oob": True},
            status_code=400,
        )
    resp = _page(request, service, None, new_note=True, import_error=message, here="/notes/new")
    resp.status_code = 400
    return resp


def _attachment(filename: str) -> str:
    """RFC 6266: an ASCII fallback, and the real name as UTF-8 in filename*.

    Headers are latin-1, so a raw non-ASCII name was a UnicodeEncodeError (500)."""
    fallback = "".join(
        c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in filename
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


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


@router.post("/theme")
async def set_theme(request: Request, theme: str = Form("system"), next: str = Form("/")):
    """Remember light/dark in a cookie (base.html reads it); "system" forgets it.

    The form names the page to return to in `next`. The Referer cannot do it:
    every page is sent with Referrer-Policy: no-referrer. Only a local path is
    followed; anything else goes to "/". The check is on the path as rebuilt:
    "////evil.example/x" splits with no netloc, but its path "//evil.example/x"
    is protocol-relative in a Location header."""
    back = urlsplit(next)
    local = not back.scheme and not back.netloc and next.startswith("/") and "\\" not in next
    path = (back.path + ("?" + back.query if back.query else "")) if local else "/"
    if path.startswith("//"):
        path = "/"
    resp = RedirectResponse(url=path, status_code=303)
    if theme in ("light", "dark"):
        resp.set_cookie("theme", theme, max_age=THEME_COOKIE_AGE, samesite="lax", httponly=True)
    else:
        resp.delete_cookie("theme")
    return resp


@router.get("/notes/new", response_class=HTMLResponse)
async def new_note_chooser(request: Request, service: NoteService = Depends(get_note_service)):
    """Add a note: empty, or from a .json / .zip file. Overlay for htmx, page otherwise."""
    if _is_htmx(request):
        return templates.TemplateResponse(request, "partials/note_new.html", _ctx(request))
    return _page(request, service, None, new_note=True)


@router.post("/notes/import")
async def import_notes(
    request: Request,
    file: UploadFile,
    service: NoteService = Depends(get_note_service),
):
    """Create new notes from an export .json or a .zip (notes.json + media/). Never merges."""
    content = await file.read()
    try:
        # Decoding images is CPU-bound; off the event loop so one import cannot stall every request.
        result = await run_in_threadpool(import_bundle, service, file.filename or "", content)
    except BundleError as e:
        return _import_refused(request, service, str(e))
    if not result.notes:
        return _import_refused(request, service, "The file contained no notes")
    for line in result.skipped:
        logger.info("import skipped %s", line)
    return _after_change(request, service, result.notes[0], headers=CLOSE_OVERLAY)


@router.get("/notes/{note_id}/export.zip")
async def export_note_zip(note_id: str, service: NoteService = Depends(get_note_service)):
    note = _note_or_404(service, note_id)
    return Response(
        export_zip(service, [note.id]),
        media_type="application/zip",
        headers={"Content-Disposition": _attachment(f"{note.name}.zip")},
    )


@router.post("/notes")
async def create_note(
    request: Request,
    title: str = Form("Untitled note"),
    service: NoteService = Depends(get_note_service),
):
    note = service.create_note(NoteCreate(title=title))
    note = service.add_chapter(note.id, title="Chapter 1") or note
    return _after_change(request, service, note, headers=CLOSE_OVERLAY)


@router.get("/notes/{note_id}", response_class=HTMLResponse)
async def fetch_note(
    note_id: str, request: Request, service: NoteService = Depends(get_note_service)
):
    return _page(request, service, _note_or_404(service, note_id))


def _delete_refused(
    request: Request,
    service: NoteService,
    note: Note,
    message: str,
    notes: list[Note],
    status_code: int = 409,
) -> Response:
    """Why the note was not deleted, on the settings: an out-of-band swap into the
    open overlay with htmx, the settings page without scripts. Deleting removes
    the note's media/ folder, so a block in another note showing one of its
    images refuses it (409), and so does a note that cannot be read (409); a
    folder that could not be removed is a 500."""
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/delete_error.html",
            {"request": request, "delete_error": message, "oob": True},
            status_code=status_code,
        )
    folders = sorted({n.folder for n in notes if n.folder})
    resp = _page(
        request,
        service,
        note,
        notes,
        settings=True,
        existing_folders=folders,
        delete_error=message,
        here=f"/notes/{note.id}/settings",
    )
    resp.status_code = status_code
    return resp


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
    try:
        note, borrowers, notes = service.delete_note_unless_shown(note_id)
    except UnreadableNotes as e:
        return _delete_refused(request, service, e.note, str(e), e.notes)
    except NoteNotRemoved as e:
        return _delete_refused(request, service, e.note, str(e), e.notes, 500)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if borrowers:
        message = (
            "Other notes show images from this note: "
            + "; ".join(borrowers)
            + ". Pick other images there first."
        )
        return _delete_refused(request, service, note, message, notes)
    return _after_change(request, service, notes[0] if notes else None, headers=CLOSE_OVERLAY)


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
            _ctx(request, note=note, chapter=chapter, media_files=_media_files(service, note)),
        )
    return _page(request, service, note, editing=chapter, media_files=_media_files(service, note))


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
    note = service.edit_chapter(
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


def _media_files(service: NoteService, note: Note, notes: list[Note] | None = None) -> list[dict]:
    """The gallery's files, each with the blocks that use it (a used file has no delete).
    Every note is read once per render, not once per file."""
    notes = service.list_notes() if notes is None else notes
    return [
        {"name": f, "users": media_users(notes, note, f)}
        for f in service.repo.list_media(note.name)
    ]


def _media_reply(
    request: Request,
    service: NoteService,
    note: Note,
    chapter_id: str,
    error: str | None = None,
    status_code: int = 200,
    notes: list[Note] | None = None,
) -> Response:
    """Gallery fragment for htmx; back to the block's edit page otherwise.

    With an error the gallery is drawn as it is now, with the reason above it:
    the fragment for htmx (app.js swaps it in despite the status), the block's
    edit page without scripts. Neither leaves the user looking at raw JSON or at
    nothing."""
    files = _media_files(service, note, notes)
    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/media_gallery.html",
            _ctx(
                request,
                active=note,
                chapter_id=chapter_id,
                media_files=files,
                media_error=error,
            ),
            status_code=status_code,
        )
    if error is None:
        return RedirectResponse(url=f"/notes/{note.id}/chapters/{chapter_id}/edit", status_code=303)
    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if chapter is None:
        raise HTTPException(status_code=status_code, detail=error)
    resp = _page(
        request,
        service,
        note,
        notes,
        editing=chapter,
        media_files=files,
        media_error=error,
        here=f"/notes/{note.id}/chapters/{chapter.id}/edit",
    )
    resp.status_code = status_code
    return resp


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
        new_filename, processed, metadata = await run_in_threadpool(
            process_uploaded_image, file.filename or "upload", content
        )
    except UnsupportedImage as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
    try:
        note, users, deleted, notes = service.delete_media_unless_used(note_id, filename)
    except UnreadableNotes as e:
        return _media_reply(
            request, service, e.note, chapter_id, error=str(e), status_code=409, notes=e.notes
        )
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if users:
        # Deleting it would leave each of these blocks requesting a file that is gone.
        # Reached from a gallery drawn before the file was picked somewhere.
        return _media_reply(
            request,
            service,
            note,
            chapter_id,
            error=f"{filename} is used by {'; '.join(users)}. Pick another image there first.",
            status_code=409,
            notes=notes,
        )
    if not deleted:
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
    note, saved, reason = service.pick_media(note_id, chapter_id, url)
    if note is None:
        raise HTTPException(status_code=404, detail="Note or block not found")
    if not saved:
        # The gallery was drawn before the file was deleted (20261021-010), or the
        # URL is a data: URL the app would not draw (20261021-023). Answer with
        # the gallery as it is now, into the gallery, not the page.
        resp = _media_reply(
            request,
            service,
            note,
            chapter_id,
            error=reason,
            status_code=409,
        )
        resp.headers["HX-Retarget"] = f"#media-gallery-{chapter_id}"
        resp.headers["HX-Reswap"] = "innerHTML"
        return resp
    return _after_change(request, service, note)
