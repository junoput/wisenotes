import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.editor.mixed_content import build_editor_json
from app.editor.mixed_content import split_mixed_content
from app.schemas import Chapter
from app.schemas import NoteCreate
from app.services.notes import NoteService
from app.web.dependencies import get_note_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, service: NoteService = Depends(get_note_service)):
    notes = service.list_notes()
    active = notes[0] if notes else None
    return templates.TemplateResponse(
        "index.html", {"request": request, "notes": notes, "active": active}
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
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
        "partials/hx_refresh.html", {"request": request, "active": note, "notes": notes}
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
    )


@router.post("/notes/{note_id}/chapters/{chapter_id}/move", response_class=HTMLResponse)
async def move_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
    parent_id: str = Form(None),
    service: NoteService = Depends(get_note_service),
):
    note = service.move_chapter(note_id, chapter_id, parent_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
    )


@router.get("/notes/{note_id}/chapters/{chapter_id}/edit", response_class=HTMLResponse)
async def edit_chapter(
    note_id: str,
    chapter_id: str,
    request: Request,
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

    return templates.TemplateResponse(
        "partials/chapter_edit_form.html", 
        {"request": request, "note": note, "chapter": chapter, "chapter_json": chapter_json}
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

        child_content, child_children = split_mixed_content(child_data.get("content"))
        
        if child_id:
            existing_child = next((c for c in existing_chapters if c.id == child_id), None)
            if existing_child:
                service.update_chapter(note_id, child_id, child_title, child_content)
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
                    service.update_chapter(note_id, child_id, child_title, child_content)
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
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    
    # Update the main chapter
    note = service.update_chapter(note_id, chapter_id, title, content_text)
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": note}
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
        "partials/hx_refresh.html", {"request": request, "notes": notes, "active": active}
    )



