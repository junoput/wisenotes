import json
from uuid import uuid4

from fastapi import APIRouter
import logging
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from app.block_types import BLOCK_TYPES
from app.editor.mixed_content import build_editor_json
from app.editor.mixed_content import split_mixed_content
from app.schemas import Chapter
from app.schemas import NoteCreate
from app.schemas import NoteUpdate
from app.services.notes import NoteService
from app.web.dependencies import get_note_service
from app.config import get_accessibility_bindings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _template_context(request: Request, **kwargs) -> dict:
    """Build template context with block types configuration."""
    ctx = {"request": request, "block_types": BLOCK_TYPES, **kwargs}
    # Include accessibility keybindings for templates and client JS
    try:
        ctx["accessibility"] = get_accessibility_bindings()
    except Exception:
        ctx["accessibility"] = {}
    return ctx


def _normalize_source_multi(value) -> Optional[str]:
    """Normalize a semicolon-separated source string.

    - Accepts None or string
    - Splits on ';', trims whitespace
    - Removes empty entries
    - Joins with '; ' for consistent storage
    - Returns None if nothing remains
    """
    if value is None:
        return None
    # If an array is provided from JSON editor, join it
    if isinstance(value, list):
        parts = [str(p).strip() for p in value]
        parts = [p for p in parts if p]
        return "; ".join(parts) if parts else None
    if not isinstance(value, str):
        return None
    parts = [p.strip() for p in value.split(";")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return "; ".join(parts)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, service: NoteService = Depends(get_note_service)):
    notes = service.list_notes()
    # Render shell with no active note; main pane stays empty until user picks a note
    return templates.TemplateResponse(
        "index.html", _template_context(request, notes=notes, active=None)
    )


@router.post("/notes", response_class=HTMLResponse)
async def create_note(
    request: Request,
    title: str = Form(...),
    service: NoteService = Depends(get_note_service),
):
    note = service.create_note(
        NoteCreate(
            title=title,
            chapters=[Chapter(id=str(uuid4()), title="Chapter 1", content="", order=0, parent_id=None)],
        )
    )
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.get("/notes/{note_id}", response_class=HTMLResponse)
async def fetch_note(
    note_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, active=note, notes=notes)
    )


@router.post("/notes/{note_id}/chapters", response_class=HTMLResponse)
async def add_chapter(
    note_id: str,
    request: Request,
    parent_id: str = Form(None),
    block_type: str = Form("chapter"),
    service: NoteService = Depends(get_note_service),
):
    note = service.add_chapter(note_id, parent_id=parent_id, block_type=block_type)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.post("/notes/{note_id}/chapters/after", response_class=HTMLResponse)
async def add_chapter_after(
    note_id: str,
    request: Request,
    prev_id: str = Form(...),
    block_type: str = Form("chapter"),
    service: NoteService = Depends(get_note_service),
):
    note = service.add_chapter_after(note_id, prev_id=prev_id, block_type=block_type)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.post("/notes/{note_id}/chapters/before", response_class=HTMLResponse)
async def add_chapter_before(
    note_id: str,
    request: Request,
    next_id: str = Form(...),
    block_type: str = Form("chapter"),
    service: NoteService = Depends(get_note_service),
):
    note = service.add_chapter_before(note_id, next_id=next_id, block_type=block_type)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.post("/notes/{note_id}/chapters/child", response_class=HTMLResponse)
async def add_chapter_child(
    note_id: str,
    request: Request,
    parent_id: str = Form(...),
    block_type: str = Form("chapter"),
    service: NoteService = Depends(get_note_service),
):
    note = service.add_chapter_child(note_id, parent_id=parent_id, block_type=block_type)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/move", response_class=HTMLResponse)
async def move_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    target_id: str = Form(""),
    parent_id: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    logger.info(
        "HTTP move_chapter request START: note=%s chapter=%s target=%s parent=%s",
        note_id, chapter_id, target_id or "(root)", parent_id or "(no parent)"
    )
    
    try:
        # Validate inputs
        if not note_id or not chapter_id:
            logger.error("HTTP move_chapter: missing note_id or chapter_id")
            raise ValueError("Missing note_id or chapter_id")
        
        logger.debug("HTTP move_chapter: calling service.move_chapter")
        note = service.move_chapter(note_id, chapter_id, target_id, parent_id or None)
        
        if not note:
            logger.error("HTTP move_chapter: service returned None (note not found)")
            raise HTTPException(status_code=404, detail="Note not found")
        
        logger.info("HTTP move_chapter: move succeeded, reloading note list")
        # Re-read from storage to ensure we get the persisted state
        notes = service.list_notes()
        
        logger.info(
            "HTTP move_chapter SUCCESS: note=%s chapter=%s moved before=%s",
            note_id, chapter_id, target_id or "(root)"
        )
        
        return templates.TemplateResponse(
            "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
        )
        
    except ValueError as e:
        logger.error(
            "HTTP move_chapter VALIDATION ERROR: note=%s chapter=%s error=%s",
            note_id, chapter_id, str(e)
        )
        raise HTTPException(status_code=400, detail=str(e))
        
    except Exception as e:
        logger.error(
            "HTTP move_chapter UNEXPECTED ERROR: note=%s chapter=%s target=%s parent=%s error=%s",
            note_id, chapter_id, target_id or "(root)", parent_id or "(none)", str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Internal server error during move operation: {str(e)}")


@router.get("/notes/{note_id}/chapters/{chapter_id}/edit", response_class=HTMLResponse)
async def edit_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    mode: str = "graphical",
    service: NoteService = Depends(get_note_service),
):
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    chapter_dict = build_editor_json(chapter, note.chapters, 0, max_depth=3)
    chapter_json = json.dumps(chapter_dict, indent=2)

    # Use JSON editor template for "JSON Editor" mode, graphical template for "Graphical Editor" mode
    template = "partials/chapter_edit_json.html" if mode == "json" else "partials/chapter_edit_form.html"
    
    return templates.TemplateResponse(
        template, 
        _template_context(request, note=note, chapter=chapter, chapter_json=chapter_json)
    )


@router.get("/notes/{note_id}/settings", response_class=HTMLResponse)
async def note_settings(
    note_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return templates.TemplateResponse(
        "partials/note_settings.html",
        _template_context(request, note=note),
    )


@router.post("/notes/{note_id}/title", response_class=HTMLResponse)
async def update_note_title(
    note_id: str,
    request: Request,
    title: str = Form(...),
    service: NoteService = Depends(get_note_service),
):
    note = service.update_note(note_id, NoteUpdate(title=title))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.get("/settings", response_class=HTMLResponse)
async def app_settings(
    request: Request,
):
    return templates.TemplateResponse(
        "partials/app_settings.html",
        _template_context(request),
    )


def _process_chapter_children(
    note_id: str,
    parent_chapter_id: str,
    children_data: list[dict],
    service: NoteService,
    existing_chapters: list[Chapter],
    depth: int = 0,
) -> list[str]:
    if depth >= 3:
        return []

    processed_ids = []

    for child_data in children_data:
        if "title" not in child_data:
            continue
        
        child_id = child_data.get("id")
        child_title = child_data["title"]
        child_language = child_data.get("language")
        child_source = _normalize_source_multi(child_data.get("source"))

        child_content, child_children = split_mixed_content(child_data.get("content"))
        
        if child_id:
            existing_child = next((c for c in existing_chapters if c.id == child_id), None)
            if existing_child:
                service.update_chapter(note_id, child_id, child_title, child_content, child_language, child_source)
                processed_ids.append(child_id)
            else:
                continue
        else:
            note = service.add_chapter_child(note_id, parent_id=parent_chapter_id)
            if note and note.chapters:
                new_child = next(
                    (c for c in reversed(note.chapters) if c.parent_id == parent_chapter_id),
                    None
                )
                if new_child:
                    child_id = new_child.id
                    service.update_chapter(note_id, child_id, child_title, child_content, child_language, child_source)
                    processed_ids.append(child_id)
                    note = service.get_note(note_id)
                    if note:
                        existing_chapters[:] = note.chapters
        
        if child_children and child_id:
            note = service.get_note(note_id)
            if note:
                existing_chapters[:] = note.chapters
            grandchild_ids = _process_chapter_children(
                note_id, child_id, child_children, service, existing_chapters, depth + 1
            )
            processed_ids.extend(grandchild_ids)
    
    return processed_ids


def _get_all_descendant_ids(chapters: list[Chapter], parent_id: str) -> list[str]:
    descendant_ids = []
    direct_children = [c for c in chapters if c.parent_id == parent_id]
    for child in direct_children:
        descendant_ids.append(child.id)
        descendant_ids.extend(_get_all_descendant_ids(chapters, child.id))
    return descendant_ids


@router.post("/notes/{note_id}/chapters/{chapter_id}/edit", response_class=HTMLResponse)
async def update_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    content: str = Form(""),
    service: NoteService = Depends(get_note_service),
):
    # Parse JSON from the form content with mixed content array
    try:
        chapter_data = json.loads(content)
        if "title" not in chapter_data:
            raise ValueError("JSON must contain 'title' field")
        title = chapter_data["title"]
        content_text, children_data = split_mixed_content(chapter_data.get("content"))
        language = chapter_data.get("language")
        source = _normalize_source_multi(chapter_data.get("source"))

    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    
    # Update the main chapter
    note = service.update_chapter(note_id, chapter_id, title, content_text, language, source)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Process children recursively
    existing_chapters = list(note.chapters)
    processed_ids = _process_chapter_children(
        note_id, chapter_id, children_data, service, existing_chapters, 0
    )
    
    # Delete children that were not in the JSON (removed by user)
    note = service.get_note(note_id)  # Refresh to get latest state
    if note:
        # Get all descendants of this chapter
        all_descendant_ids = _get_all_descendant_ids(note.chapters, chapter_id)
        # Delete any descendants that weren't processed
        for desc_id in all_descendant_ids:
            if desc_id not in processed_ids:
                service.delete_chapter(note_id, desc_id)
    
    # Final refresh
    note = service.get_note(note_id)
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=note)
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/delete", response_class=HTMLResponse)
async def delete_chapter_route(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    deleted_note = service.delete_chapter(note_id, chapter_id)
    if deleted_note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    # Keep the current note active (deleted_note) if it still exists
    return templates.TemplateResponse(
        "partials/hx_refresh.html", _template_context(request, notes=notes, active=deleted_note)
    )


@router.delete("/notes/{note_id}", response_class=HTMLResponse)
async def delete_note(
    note_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    deleted = service.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    active = notes[0] if notes else None
    return templates.TemplateResponse(
        "partials/hx_refresh.html",
        _template_context(request, notes=notes, active=active),
        headers={"HX-Trigger": "close-note-settings"},
    )


@router.get("/{note_name}", response_class=HTMLResponse)
async def fetch_note_by_name(
    note_name: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    # Look up note by its unique name (stored by the repository)
    notes = service.list_notes()
    note = next((n for n in notes if n.name == note_name), None)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    # Serve full page for direct navigation, partial for HTMX swaps
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(
            "partials/hx_refresh.html", _template_context(request, active=note, notes=notes)
        )
    return templates.TemplateResponse(
        "index.html", _template_context(request, active=note, notes=notes)
    )


@router.get("/{note_name}/{chapter_id}", response_class=HTMLResponse)
async def fetch_chapter_by_id(
    note_name: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    # Look up note by name
    notes = service.list_notes()
    note = next((n for n in notes if n.name == note_name), None)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    # Verify chapter exists in this note
    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # Serve full page for direct navigation, partial for HTMX swaps
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(
            "partials/hx_refresh.html", _template_context(request, active=note, notes=notes)
        )
    return templates.TemplateResponse(
        "index.html", _template_context(request, active=note, notes=notes)
    )


@router.post("/notes/{note_id}/media/upload", response_class=HTMLResponse)
async def upload_media_form(
    note_id: str,
    file: UploadFile,
    request: Request,
    service: NoteService = Depends(get_note_service),
) -> None:
    """Upload media file and return updated gallery."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    
    # Save media
    service.repo.save_media(note.name, file.filename, content)
    
    # Get updated media list
    media_files = service.repo.list_media(note.name)
    
    # Return updated gallery
    return templates.TemplateResponse(
        "partials/media_gallery.html",
        _template_context(
            request,
            active=note,
            media_files=media_files
        )
    )


@router.get("/notes/{note_id}/chapters/{chapter_id}/media/browser", response_class=HTMLResponse)
async def media_browser(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    """Render media browser panel for a chapter."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # Get list of media files
    media_files = service.repo.list_media(note.name)
    
    return templates.TemplateResponse(
        "partials/media_browser_panel.html",
        _template_context(
            request,
            active=note,
            chapter=chapter,
            chapter_id=chapter_id,
            media_files=media_files
        )
    )


@router.get("/notes/{note_id}/chapters/{chapter_id}/media/picker", response_class=HTMLResponse)
async def media_picker_inline(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    """Render inline media picker inside the editor pane."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    media_files = service.repo.list_media(note.name)

    return templates.TemplateResponse(
        "partials/media_picker_inline.html",
        _template_context(
            request,
            active=note,
            chapter=chapter,
            chapter_id=chapter_id,
            media_files=media_files,
        ),
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/media/select", response_class=HTMLResponse)
async def select_media(
    note_id: str,
    chapter_id: str,
    request: Request,
    url: str = Form(...),
    service: NoteService = Depends(get_note_service),
):
    """Handle media selection and update chapter."""
    note = service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    chapter = next((c for c in note.chapters if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # Update chapter content with media URL
    service.update_chapter(
        note_id, 
        chapter_id, 
        title=chapter.title,
        content=url,
        language=chapter.language,
        source=chapter.source
    )
    
    # Return updated note
    note = service.get_note(note_id)
    return templates.TemplateResponse(
        "partials/hx_refresh.html",
        _template_context(request, active=note, notes=service.list_notes())
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/move-up", response_class=HTMLResponse)
async def move_chapter_up(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    """Move a chapter up within its siblings."""
    note = service.move_chapter_up(note_id, chapter_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html",
        _template_context(request, active=note, notes=notes)
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/move-down", response_class=HTMLResponse)
async def move_chapter_down(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    """Move a chapter down within its siblings."""
    note = service.move_chapter_down(note_id, chapter_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html",
        _template_context(request, active=note, notes=notes)
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/indent", response_class=HTMLResponse)
async def indent_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    """Indent a chapter (nest inside previous sibling)."""
    note = service.indent_chapter(note_id, chapter_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html",
        _template_context(request, active=note, notes=notes)
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/outdent", response_class=HTMLResponse)
async def outdent_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    service: NoteService = Depends(get_note_service),
):
    """Outdent a chapter (move out of parent)."""
    note = service.outdent_chapter(note_id, chapter_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html",
        _template_context(request, active=note, notes=notes)
    )


