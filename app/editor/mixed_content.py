from __future__ import annotations

from typing import Any

from app.schemas import Chapter


def split_mixed_content(value: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(value, list):
        text_parts: list[str] = []
        children: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                children.append(item)
        content_text = "\n\n".join([t for t in text_parts if t])
        return content_text, children

    if isinstance(value, str):
        return value, []

    return "", []


def build_editor_json(chapter: Chapter, all_chapters: list[Chapter], depth: int = 0, max_depth: int = 3) -> dict[str, Any]:
    children = [c for c in all_chapters if c.parent_id == chapter.id]
    children.sort(key=lambda c: c.order)

    result: dict[str, Any] = {"id": chapter.id, "title": chapter.title, "type": chapter.type, "content": []}
    
    # Include language if it exists
    if chapter.language:
        result["language"] = chapter.language
    # Include source if it exists
    if chapter.source:
        result["source"] = chapter.source

    if chapter.content:
        result["content"].append(chapter.content)

    if children and depth < max_depth:
        for child in children:
                result["content"].append(build_editor_json(child, all_chapters, depth + 1, max_depth=max_depth))

    return result
