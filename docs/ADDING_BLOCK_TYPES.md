# Adding New Block Types

This guide explains how to add a new block type to Wisenotes.

## Overview

Block types in Wisenotes are modular and configured through a central system. Adding a new block type requires updates to:

1. Block type configuration (`app/block_types.py`)
2. CSS styling (`app/static/css/style.css`)
3. Display rendering (optional, for special display needs)
4. Form fields (optional, for type-specific inputs)

## Step 1: Add Block Type Configuration

Edit `app/block_types.py` and add your new type to the `BLOCK_TYPES` dictionary:

```python
BLOCK_TYPES: dict[str, BlockTypeConfig] = {
    # ... existing types ...
    "diagram": BlockTypeConfig(
        name="diagram",           # Internal identifier
        emoji="📊",               # Button emoji
        color="#10b981",          # Border and button color (hex)
        can_nest=False,           # Can this type have children?
        default_language="mermaid",  # Optional: for language selector
        language_options=["mermaid", "plantuml"],  # Optional: language choices
    ),
}
```

### Configuration Options

- **name**: Internal identifier (must match schema enum)
- **emoji**: Symbol shown on add buttons
- **color**: Hex color for borders and UI elements
- **can_nest**: Whether this block can have child blocks
- **default_language**: Default language for language-specific blocks (optional)
- **language_options**: List of available languages for this type (optional)

## Step 2: Update Schema

Edit `app/schemas.py` to add your type to the `BlockType` Literal:

```python
BlockType = Literal["chapter", "paragraph", "code", "math", "diagram"]
```

## Step 3: Add CSS Styling

Edit `app/static/css/style.css` to add color styling for your type:

```css
/* Add to root variables */
:root {
  /* ... existing colors ... */
  --color-diagram: #10b981;
}

/* Add border color for blocks */
.chapter-item-container[data-chapter-type="diagram"] {
  border-left-color: var(--color-diagram) !important;
}

/* Add button color */
.add-btn-type[data-type="diagram"] {
  background: var(--color-diagram);
  color: #0f172a;
}

/* Add permanent button color */
.add-btn-permanent-type[data-type="diagram"] {
  background: var(--color-diagram);
  color: #0f172a;
}
```

## Step 4: Add Display Rendering (Optional)

If your block type needs special rendering (like code blocks with syntax highlighting or math formulas), add a display template in `app/templates/components/editor_chapters.html`:

```html
{% elif chapter.type == 'diagram' %}
  <div class="block-content diagram-block-display" 
       data-language="{{ chapter.language or 'mermaid' }}"
       data-chapter-id="{{ chapter.id }}">
    <div class="diagram-content">{{ chapter.content }}</div>
  </div>
```

Then add JavaScript initialization in `app/static/js/app.js`:

```javascript
function initializeDiagramBlocks() {
    document.querySelectorAll('.diagram-block-display:not([data-initialized])').forEach(block => {
        try {
            const content = block.querySelector('.diagram-content').textContent;
            const language = block.dataset.language || 'mermaid';
            
            // Your rendering logic here
            // Example: mermaid.render(content, block);
            
            block.dataset.initialized = 'true';
        } catch (error) {
            console.error('Diagram rendering error:', error);
        }
    });
}

// Add to initialization
document.addEventListener('DOMContentLoaded', initializeDiagramBlocks);
htmx.on('htmx:afterSwap', initializeDiagramBlocks);
```

## Step 5: Add Form Fields (Optional)

If your type needs special form inputs, update `app/templates/partials/chapter_edit_form.html`:

```html
{% if block_type == 'diagram' %}
  <label for="language">Diagram Type:</label>
  <select id="language" name="language">
    {% for lang in block_types['diagram'].language_options %}
      <option value="{{ lang }}" {% if chapter.language == lang %}selected{% endif %}>
        {{ lang|capitalize }}
      </option>
    {% endfor %}
  </select>
{% endif %}
```

## Step 6: Test Your Block Type

1. Restart the server:
   ```bash
   docker compose restart
   ```

2. Create a note and add your new block type

3. Verify:
   - Add buttons show correct emoji and color
   - Block displays with correct border color
   - Special rendering works (if applicable)
   - Language selector appears (if applicable)
   - Edit and save works correctly

## Complete Example: Adding a Table Block

Here's a complete example of adding a simple table block:

### 1. Block configuration (`app/block_types.py`):
```python
"table": BlockTypeConfig(
    name="table",
    emoji="⊞",
    color="#8b5cf6",
    can_nest=False,
    default_language="markdown",
    language_options=["markdown", "html", "csv"],
),
```

### 2. Schema (`app/schemas.py`):
```python
BlockType = Literal["chapter", "paragraph", "code", "math", "table"]
```

### 3. CSS (`app/static/css/style.css`):
```css
:root {
  --color-table: #8b5cf6;
}

.chapter-item-container[data-chapter-type="table"] {
  border-left-color: var(--color-table) !important;
}

.add-btn-type[data-type="table"] {
  background: var(--color-table);
  color: #0f172a;
}

.add-btn-permanent-type[data-type="table"] {
  background: var(--color-table);
  color: #0f172a;
}
```

### 4. Display (optional, if you want special table rendering):
```html
{% elif chapter.type == 'table' %}
  <div class="block-content table-block-display" 
       data-language="{{ chapter.language or 'markdown' }}">
    <pre>{{ chapter.content }}</pre>
  </div>
```

That's it! Your new block type is ready to use.

## Troubleshooting

- **Block type not appearing**: Check that the name in `BLOCK_TYPES` matches the schema Literal
- **Wrong color**: Verify CSS variable name matches pattern `--color-{typename}`
- **Language selector not showing**: Ensure `language_options` is set in configuration
- **Children not allowed**: Set `can_nest=True` in configuration

## Best Practices

1. **Use descriptive emojis**: Choose emojis that clearly represent the block type
2. **Pick distinct colors**: Ensure the color is visually distinct from existing types
3. **Keep rendering simple**: Complex rendering should be done client-side
4. **Follow naming conventions**: Use lowercase, single-word names for types
5. **Document special features**: If your type has unique behavior, document it
