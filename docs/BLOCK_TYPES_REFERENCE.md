# Block Types Quick Reference

## Current Block Types

| Type | Emoji | Color | Can Nest | Languages |
|------|-------|-------|----------|-----------|
| chapter | 📄 | #22d3ee (cyan) | ✅ Yes | - |
| paragraph | ¶ | #64748b (slate) | ❌ No | - |
| code | {} | #f59e0b (orange) | ❌ No | python, javascript, typescript, go, rust |
| math | ∑ | #a78bfa (purple) | ❌ No | latex, asciimath |

## Configuration Location

**File:** `app/block_types.py`

## Adding a New Type (Summary)

1. **Add to `app/block_types.py`:**
   ```python
   "newtype": BlockTypeConfig(
       name="newtype",
       emoji="🎨",
       color="#hexcolor",
       can_nest=False,
   ),
   ```

2. **Update schema in `app/schemas.py`:**
   ```python
   BlockType = Literal["chapter", "paragraph", "code", "math", "newtype"]
   ```

3. **Add CSS in `app/static/css/style.css`:**
   ```css
   :root {
     --color-newtype: #hexcolor;
   }
   
   .chapter-item-container[data-chapter-type="newtype"] {
     border-left-color: var(--color-newtype) !important;
   }
   
   .add-btn-type[data-type="newtype"] {
     background: var(--color-newtype);
     color: #0f172a;
   }
   ```

4. **Optional:** Add special rendering or form fields

5. **Restart:** `docker compose restart`

## Full Documentation

See [ADDING_BLOCK_TYPES.md](./ADDING_BLOCK_TYPES.md) for complete guide with examples.

## API Functions

```python
from app.block_types import (
    BLOCK_TYPES,              # Dict of all block type configs
    get_block_type_config,    # Get config for a type
    get_default_language,     # Get default language
    can_have_children,        # Check if type can nest
)
```

## Template Access

All templates have access to `block_types` variable:

```jinja2
{% for type_name, type_config in block_types.items() %}
  {{ type_config.emoji }} {{ type_config.name }}
{% endfor %}
```
