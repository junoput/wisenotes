# Modular Block System

This document describes how to add, modify, or remove block types in Wisenotes.

## Architecture Overview

Each block type lives in its own folder under `app/blocks/<block_name>/`:

```
app/blocks/
├── __init__.py          # Exports registry functions
├── base.py              # BaseBlock class definition
├── registry.py          # Auto-discovery and registration
├── chapter/             # Container block (special)
│   ├── block.py
│   └── templates/
│       ├── display.html
│       └── edit.html
├── code/                # Code block with syntax highlighting
│   ├── block.py
│   └── templates/
├── math/                # Mathematical formulas
│   ├── block.py
│   └── templates/
├── media/               # Images and media files
│   ├── block.py
│   └── templates/
├── paragraph/           # Simple text paragraphs
│   ├── block.py
│   └── templates/
└── text/                # Default fallback block
    ├── block.py
    └── templates/
```

## Adding a New Block Type

1. **Create the folder structure:**
   ```bash
   mkdir -p app/blocks/myblock/templates
   ```

2. **Create `block.py`** with your block configuration:
   ```python
   from dataclasses import dataclass, field
   from app.blocks.base import BaseBlock

   @dataclass
   class MyBlock(BaseBlock):
       name: str = "myblock"           # Unique identifier
       display_name: str = "My Block"  # Human-readable name
       emoji: str = "🎯"               # Icon for UI
       color: str = "#10b981"          # Accent color
       
       can_nest: bool = False          # Can contain children?
       is_container: bool = False      # Is structural container?
       
       editor: str = "textarea"        # Editor: 'textarea', 'codemirror', 'media'
       default_language: str | None = None
       language_options: list[str] = field(default_factory=list)

   # Export singleton for auto-discovery
   block = MyBlock()
   ```

3. **Create display template** (`templates/display.html`):
   ```html
   <div class="block-content myblock-block-display">
     {{ chapter.content }}
   </div>
   ```

4. **Create edit template** (`templates/edit.html`):
   ```html
   <div class="field">
     <textarea id="content-{{ chapter.id }}"
               name="content_text"
               rows="10"
               data-editor-target
               placeholder="Enter content">{{ chapter.content }}</textarea>
   </div>
   ```

5. **Restart the app** — the block is auto-discovered!

## Block Properties

| Property | Type | Description |
|----------|------|-------------|
| `name` | `str` | Unique identifier (folder name) |
| `display_name` | `str` | Human-readable name for UI |
| `emoji` | `str` | Icon shown in menus |
| `color` | `str` | Accent color (hex) |
| `can_nest` | `bool` | Can this block contain children? |
| `is_container` | `bool` | Is this a structural container? |
| `editor` | `str` | Editor type: `textarea`, `codemirror`, `media` |
| `default_language` | `str \| None` | Default language for code/math |
| `language_options` | `list[str]` | Available languages |
| `js_modules` | `list[str]` | JS files to load |
| `css_modules` | `list[str]` | CSS files to load |

## Special Blocks

### Chapter Block (`chapter`)
- The only block type allowed at root level
- Can contain nested child blocks (`can_nest=True`, `is_container=True`)
- Has a required title

### Text Block (`text`)
- Default fallback for unknown block types
- Simple text area editor

## Unknown Block Types

When a block with an unknown `type` is loaded (e.g., from imported data), it automatically falls back to the `text` block for display and editing.

## API Usage

```python
from app.blocks import get_block, get_all_blocks, get_block_choices

# Get a specific block config
code_block = get_block("code")
print(code_block.emoji)  # "{}"
print(code_block.editor)  # "codemirror"

# Get all registered blocks
all_blocks = get_all_blocks()

# Get choices for UI menus
choices = get_block_choices()  # [(name, display_name, emoji), ...]

# Unknown types fallback to text
unknown = get_block("nonexistent")
print(unknown.name)  # "text"
```
