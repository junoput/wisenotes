/**
 * Dynamically load and instantiate editor class
 */
console.log('[app.js] loaded');

// Import media picker initialization (use absolute paths from /static/js/)
import { initMediaPickersOnPage } from '/static/js/media-picker.js';
import { initDragAndDrop } from '/static/js/drag-drop.js';

console.log('[app.js] imports completed, initDragAndDrop=', typeof initDragAndDrop);

// Top-level capturing key logger (runs even before DOMContentLoaded handlers)
window.addEventListener('keydown', (e) => {
  try {
    console.log('[keylog-top] key pressed', {
      key: e.key,
      code: e.code,
      ctrl: e.ctrlKey,
      alt: e.altKey,
      shift: e.shiftKey,
      meta: e.metaKey,
    });
  } catch (err) {
    // ignore errors
  }
}, true);
// Create a small visible indicator in the bottom-right corner to show last key
try {
  const _keyIndicator = document.createElement('div');
  _keyIndicator.id = 'wisenotes-key-indicator';
  _keyIndicator.style.position = 'fixed';
  _keyIndicator.style.right = '12px';
  _keyIndicator.style.bottom = '12px';
  _keyIndicator.style.zIndex = '9999';
  _keyIndicator.style.background = 'rgba(0,0,0,0.6)';
  _keyIndicator.style.color = 'white';
  _keyIndicator.style.padding = '6px 10px';
  _keyIndicator.style.borderRadius = '6px';
  _keyIndicator.style.fontFamily = 'monospace';
  _keyIndicator.style.fontSize = '12px';
  _keyIndicator.style.pointerEvents = 'none';
  _keyIndicator.textContent = '';
  document.addEventListener('DOMContentLoaded', () => {
    document.body.appendChild(_keyIndicator);
  });
  window.addEventListener('keydown', (e) => {
    const parts = [];
    if (e.ctrlKey) parts.push('Ctrl');
    if (e.altKey) parts.push('Alt');
    if (e.shiftKey) parts.push('Shift');
    if (e.metaKey) parts.push('Meta');
    parts.push(e.key);
    _keyIndicator.textContent = parts.join('+');
  }, true);
} catch (err) {
  // ignore failures
}

// Focus helper: moves focus to the first note in the list
function focusFirstNoteItem() {
  try {
    const marker = document.querySelector('[data-focus-first]');
    const firstNote = marker || document.querySelector('.note-list .item');
    if (firstNote && firstNote.focus) {
      firstNote.focus({ preventScroll: true });
    }
  } catch (err) {
    console.warn('focusFirstNoteItem error', err);
  }
}

// Shift-only navigation: press Shift to move focus to next chapter-section
function _isTypingElement(el) {
  if (!el) return false;
  const tag = (el.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (el.isContentEditable) return true;
  return false;
}

function _focusNextChapter() {
  const chapters = Array.from(document.querySelectorAll('.chapter-section'));
  if (!chapters.length) return;
  const active = document.activeElement;
  let idx = chapters.indexOf(active);
  if (idx === -1) {
    chapters[0].focus();
    return;
  }
  const next = chapters[(idx + 1) % chapters.length];
  next.focus();
}

window.addEventListener('keydown', (e) => {
  try {
    // Only act when the bare Shift key is pressed (no other modifiers)
    if (e.key === 'Shift' && !e.ctrlKey && !e.altKey && !e.metaKey && !e.repeat) {
      // Ignore if typing in an input-like element
      const active = document.activeElement;
      if (_isTypingElement(active)) return;
        e.preventDefault();
        // If focus is already inside a chapter-section, continue chapter cycling
        if (active && active.closest && active.closest('.chapter-section')) {
          _focusNextChapter();
          return;
        }
        // Otherwise, always try to focus the first note; if none, fallback to chapters
        if (focusFirstNoteItem) {
          focusFirstNoteItem();
          return;
        }
        _focusNextChapter();
    }
  } catch (err) {
    console.warn('Shift navigation error', err);
  }
}, true);

// After HTMX swaps that touch the note list, restore focus to the first note
document.body.addEventListener('htmx:afterSwap', (e) => {
  try {
    const target = (e.detail && e.detail.target) || e.target;
    const isNoteListSwap = target && (target.id === 'note-list' || (target.closest && target.closest('#note-list')));
    if (isNoteListSwap) {
      setTimeout(() => focusFirstNoteItem(), 0);
    }
  } catch (err) {
    console.warn('afterSwap focus error', err);
  }
});

// Update main-container class based on whether a note is open
function updateMainContainerClass() {
  try {
    const mainContainer = document.querySelector('.main-container');
    const editor = document.getElementById('editor');
    if (mainContainer && editor) {
      const hasActiveNote = editor.hasAttribute('data-note-id');
      if (hasActiveNote) {
        mainContainer.classList.remove('no-note-open');
      } else {
        mainContainer.classList.add('no-note-open');
      }
    }
  } catch (err) {
    console.warn('updateMainContainerClass error', err);
  }
}

// Update on page load
document.addEventListener('DOMContentLoaded', updateMainContainerClass);

// Update after any HTMX swap
document.body.addEventListener('htmx:afterSwap', updateMainContainerClass);

// When Enter is pressed on a focused note item, trigger its click (hx-get)
window.addEventListener('keydown', (e) => {
  try {
    if (e.key === 'Enter' && !e.repeat) {
      const active = document.activeElement;
      if (!active) return;
      // If in an input-like element, ignore
      if (_isTypingElement(active)) return;
      // Ignore if inside a form (editor form)
      if (active.closest && active.closest('form')) return;
      const item = active.closest && active.closest('.item');
      if (item) {
        e.preventDefault();
        // If item has an hx-get attribute, navigate there as a full page
        const notePath = item.getAttribute && item.getAttribute('data-note-path');
        if (notePath) {
          const targetUrl = notePath.startsWith('http') ? notePath : (window.location.origin + notePath);
          console.log('[nav] navigating to notePath', targetUrl);
          window.location.assign(targetUrl);
        } else {
          const hxGet = item.getAttribute && item.getAttribute('hx-get');
          if (hxGet) {
            const targetUrl = hxGet.startsWith('http') ? hxGet : (window.location.origin + hxGet);
            console.log('[nav] navigating to hx-get', targetUrl);
            window.location.assign(targetUrl);
          } else {
            // Fallback to click which lets HTMX handle it when available
            console.log('[nav] fallback: clicking item');
            item.click();
          }
        }
      }
    }
  } catch (err) {
    console.warn('Enter key handler error', err);
  }
}, true);
async function loadEditorClass(editorType) {
  switch (editorType) {
    case 'codemirror': {
      // Legacy fallback - JSON editor still uses generic CodeMirror
      const { CodeMirrorEditor } = await import('./editors/codemirror-editor.js');
      return CodeMirrorEditor;
    }
    case 'code-block': {
      // Code blocks use their own self-contained editor
      // The module is already loaded via block's js_modules, check registry
      if (window.editorRegistry && window.editorRegistry['code-block']) {
        return window.editorRegistry['code-block'];
      }
      // Fallback: dynamically import if not registered
      const { CodeBlockEditor } = await import('/static/blocks/code/code-block-editor.js');
      return CodeBlockEditor;
    }
    case 'textarea':
    default: {
      const { TextareaEditor } = await import('./editors/textarea-editor.js');
      return TextareaEditor;
    }
  }
}

// --- Token Input (chip) component for semicolon-separated sources ---
function initializeTokenInputs(root = document) {
  const fields = root.querySelectorAll('[data-token-input]');
  fields.forEach(setupTokenField);
}

function setupTokenField(field) {
  if (field._tokenSetup) return;
  const listEl = field.querySelector('.token-list');
  const textEl = field.querySelector('.token-input-text');
  const hiddenEl = field.querySelector('input[type="hidden"][name]');
  if (!listEl || !textEl || !hiddenEl) return;

  const tokens = [];

  // Initialize tokens from hidden field if present
  if (hiddenEl.value) {
    hiddenEl.value.split(';').map(s => s.trim()).filter(Boolean).forEach(v => tokens.push(v));
  }

  function renderTokens() {
    listEl.innerHTML = '';
    tokens.forEach((t, idx) => {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = t;
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'chip-remove';
      x.setAttribute('aria-label', `Remove ${t}`);
      x.textContent = '×';
      x.addEventListener('click', () => {
        tokens.splice(idx, 1);
        updateHidden();
        renderTokens();
        textEl.focus();
      });
      chip.appendChild(x);
      listEl.appendChild(chip);
    });
  }

  function updateHidden() {
    hiddenEl.value = tokens.join('; ');
  }

  function commitFromInput(force = false) {
    let val = textEl.value;
    if (!val && !force) return;
    const parts = val.split(';').map(s => s.trim()).filter(Boolean);
    const endsWithSemi = /;\s*$/.test(val);
    const addCount = (endsWithSemi || force) ? parts.length : Math.max(parts.length - 1, 0);
    for (let i = 0; i < addCount; i++) {
      const candidate = parts[i];
      if (candidate && !tokens.includes(candidate)) tokens.push(candidate);
    }
    const remainder = (endsWithSemi || force) ? '' : (parts.length ? parts[parts.length - 1] : '');
    textEl.value = remainder;
    updateHidden();
    renderTokens();
  }

  renderTokens();

  textEl.addEventListener('keydown', (e) => {
    if (e.key === ' ') {
      const val = textEl.value;
      if (/;\s*$/.test(val) || val.includes(';')) {
        e.preventDefault();
        commitFromInput();
      }
    } else if (e.key === ';') {
      // Defer actual commit to input/blur handlers
      setTimeout(() => commitFromInput(), 0);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      commitFromInput(true);
    } else if (e.key === 'Backspace' && textEl.selectionStart === 0 && textEl.selectionEnd === 0) {
      if (tokens.length > 0) {
        tokens.pop();
        updateHidden();
        renderTokens();
      }
    }
  });

  textEl.addEventListener('input', () => {
    const val = textEl.value;
    if (/;\s/.test(val)) {
      commitFromInput();
    }
  });

  textEl.addEventListener('blur', () => {
    commitFromInput(true);
  });

  textEl.addEventListener('paste', (e) => {
    const pasted = (e.clipboardData || window.clipboardData)?.getData('text');
    if (pasted && pasted.includes(';')) {
      e.preventDefault();
      textEl.value += pasted;
      commitFromInput();
    }
  });

  field._tokenSetup = true;
}

function synchronizeAllTokenInputs(scope = document) {
  const fields = scope.querySelectorAll('[data-token-input]');
  fields.forEach((field) => {
    const textEl = field.querySelector('.token-input-text');
    if (textEl && textEl.value) {
      textEl.dispatchEvent(new Event('blur'));
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  // Delay a tick to ensure HTMX-rendered lists are present
  setTimeout(() => focusFirstNoteItem(), 0);
  // Global capturing key logger: logs every keypress (key, code, modifiers)
  document.addEventListener('keydown', (e) => {
    try {
      console.log('[keylog] key pressed', {
        key: e.key,
        code: e.code,
        ctrl: e.ctrlKey,
        alt: e.altKey,
        shift: e.shiftKey,
        meta: e.metaKey,
      });
    } catch (err) {
      // swallow errors to avoid breaking other handlers
      console.warn('Keylog error', err);
    }
  }, true); // use capture to run before other handlers that may stop propagation
  const root = document.documentElement;

  // Editor mode switching
  const editorModeSelect = document.getElementById('editor-mode-select');
  const savedEditorMode = localStorage.getItem('editor-mode') || 'graphical';
  let jsonCodeMirrorInstance = null;
  
  if (editorModeSelect) {
    editorModeSelect.value = savedEditorMode;
    applyEditorMode(savedEditorMode);
    
    editorModeSelect.addEventListener('change', (e) => {
      const mode = e.target.value;
      localStorage.setItem('editor-mode', mode);
      applyEditorMode(mode);
    });
  }

  async function applyEditorMode(mode) {
    const graphicalView = document.getElementById('graphical-editor-view');
    const jsonView = document.getElementById('json-editor-view');

    if (!graphicalView || !jsonView) return;

    if (mode === 'json') {
      graphicalView.style.display = 'none';
      jsonView.style.display = 'block';
      await initializeJsonCodeMirror();
    } else {
      graphicalView.style.display = 'block';
      jsonView.style.display = 'none';
    }
  }

  async function initializeCodeBlockDisplays() {
    try {
      // Ensure CodeMirror is loaded
      if (!window.CodeMirror) {
        await loadCodeMirrorLibrary();
      }

      const containers = document.querySelectorAll('.code-block-display');
      for (const container of containers) {
        try {
          if (container._cmInitialized) continue;

          const textarea = container.querySelector('.code-block-textarea');
          const language = container.dataset.language || 'python';

          if (!textarea) continue;

          const mimeMap = {
            'python': 'text/x-python',
            'javascript': 'text/javascript',
            'typescript': 'text/typescript',
            'go': 'text/x-go',
            'rust': 'text/x-rustsrc',
            'java': 'text/x-java'
          };

          const modeMap = {
            'python': 'python',
            'javascript': 'javascript',
            'typescript': 'javascript',
            'go': 'go',
            'rust': 'rust',
            'java': 'clike'
          };

          const mode = modeMap[language] || 'javascript';
          const mime = mimeMap[language] || 'text/javascript';

          // Load language mode if needed
          const modeFiles = {
            'python': '/static/vendor/codemirror/python.js',
            'javascript': '/static/vendor/codemirror/javascript.js',
            'go': '/static/vendor/codemirror/go.js',
            'rust': '/static/vendor/codemirror/rust.js',
            'java': '/static/vendor/codemirror/java.js',
          };

          const scriptId = `cm-mode-${mode}`;
          if (!document.getElementById(scriptId) && modeFiles[mode]) {
            await new Promise((resolve) => {
              const script = document.createElement('script');
              script.id = scriptId;
              script.src = modeFiles[mode];
              script.onload = resolve;
              script.onerror = resolve;
              document.head.appendChild(script);
            });
          }

          // Clear container
          container.innerHTML = '';

          // Create read-only CodeMirror instance
          const cm = window.CodeMirror(container, {
            value: textarea.value,
            mode: mime,
            lineNumbers: true,
            readOnly: true,
            indentUnit: 2,
            tabSize: 2,
            indentWithTabs: false,
            theme: 'dracula',
            lineWrapping: true,
          });

          container._cmInitialized = true;
          container._cm = cm;
        } catch (err) {
          console.warn('Failed to initialize code block display:', err);
        }
      }
    } catch (err) {
      console.warn('Code block initialization failed:', err);
    }
  }

  function initializeMathBlocks() {
    try {
      if (typeof katex === 'undefined') {
        console.warn('KaTeX not loaded yet, will retry');
        return;
      }

      const mathBlocks = document.querySelectorAll('.math-block-display');
      
      mathBlocks.forEach((block) => {
        if (block._mathInitialized) return;

        const content = block.querySelector('.math-formula-content');
        const language = block.dataset.language || 'latex';
        
        if (!content) return;

        const formula = content.textContent.trim();
        if (!formula) return;

        try {
          // Clear existing content
          content.innerHTML = '';

          // Render based on language
          if (language === 'latex') {
            // Display mode (centered, large) for LaTeX
            katex.render(formula, content, {
              displayMode: true,
              throwOnError: false,
              errorColor: '#f87171',
              trust: false,
            });
          } else if (language === 'asciimath') {
            // For AsciiMath, we need to convert it first or use a different renderer
            // For now, we'll treat it as inline LaTeX
            katex.render(formula, content, {
              displayMode: false,
              throwOnError: false,
              errorColor: '#f87171',
              trust: false,
            });
          }

          block._mathInitialized = true;
        } catch (err) {
          console.warn('Failed to render math formula:', err);
          content.textContent = formula; // Fallback to plain text
        }
      });
    } catch (err) {
      console.warn('Math block initialization failed:', err);
    }
  }

  async function initializeJsonCodeMirror() {
    if (jsonCodeMirrorInstance) {
      jsonCodeMirrorInstance.refresh();
      return;
    }

    const textarea = document.getElementById('json-editor-textarea');
    const wrapper = document.getElementById('json-codemirror-wrapper');

    if (!textarea || !wrapper) return;
    if (jsonCodeMirrorInstance) return;

    // Load CodeMirror if not loaded
    await loadCodeMirrorLibrary();

    // Create CodeMirror instance
    jsonCodeMirrorInstance = window.CodeMirror(wrapper, {
      value: textarea.value,
      mode: 'application/json',
      lineNumbers: true,
      indentUnit: 2,
      tabSize: 2,
      indentWithTabs: false,
      theme: 'dracula',
      lineWrapping: true,
      gutters: ['CodeMirror-linenumbers', 'CodeMirror-lint-markers'],
      lint: true,
      autoCloseBrackets: true,
      foldGutter: true,
    });

    // Sync changes back to textarea
    jsonCodeMirrorInstance.on('change', (cm) => {
      textarea.value = cm.getValue();
    });

    // Set proper height
    jsonCodeMirrorInstance.setSize(null, '500px');
  }

  async function loadCodeMirrorLibrary() {
    ensureCss('cm-core-css', '/static/vendor/codemirror/codemirror.css');
    ensureCss('cm-theme-css', '/static/vendor/codemirror/dracula.css');
    ensureCss('cm-lint-css', '/static/vendor/codemirror/addon/lint/lint.css');

    if (!window.CodeMirror) {
      await loadScriptOnce('cm-core-js', '/static/vendor/codemirror/codemirror.js');
    }

    // Mode + addons for JSON linting and brackets
    await loadScriptOnce('cm-mode-json', '/static/vendor/codemirror/javascript.js');
    await loadScriptOnce('cm-lint-js', '/static/vendor/codemirror/addon/lint/lint.js');
    await loadScriptOnce('cm-jsonlint', '/static/vendor/codemirror/addon/lint/jsonlint.js');
    await loadScriptOnce('cm-json-lint-bridge', '/static/vendor/codemirror/addon/lint/json-lint.js');
    await loadScriptOnce('cm-closebrackets', '/static/vendor/codemirror/addon/edit/closebrackets.js');
  }

  function buildChapterJsonPayload(editForm) {
    const payloadInput = editForm.querySelector('.chapter-json-payload');
    if (!payloadInput) return;

    const title = editForm.querySelector('input[name="title"]')?.value || '';
    const sourceHidden = editForm.querySelector('input[name="source"]');
    const sourceText = editForm.querySelector('.token-input-text');
    let sourceValue = sourceHidden?.value || '';
    // Fallback 1: if hidden is empty, gather current chips
    if (!sourceValue) {
      const tokenField = editForm.querySelector('[data-token-input]');
      if (tokenField) {
        const chips = Array.from(tokenField.querySelectorAll('.chip'));
        const values = chips.map(chip => chip.childNodes[0]?.textContent?.trim() || '').filter(Boolean);
        if (values.length) {
          sourceValue = values.join('; ');
          if (sourceHidden) sourceHidden.value = sourceValue;
        }
      }
    }

    // Fallback 2: if still empty, split whatever is in the text box
    if (!sourceValue && sourceText && sourceText.value) {
      const parts = sourceText.value.split(';').map(s => s.trim()).filter(Boolean);
      if (parts.length) {
        sourceValue = parts.join('; ');
        if (sourceHidden) sourceHidden.value = sourceValue;
      }
    }

    console.log('[sources] build payload', {
      title,
      sourceValue,
      hiddenValue: sourceHidden?.value,
      textValue: sourceText?.value,
    });
    const contentField = editForm.querySelector('[data-editor-target]');
    const languageField = editForm.querySelector('select[name="language"], input[name="language"]');
    const language = languageField ? languageField.value || '' : '';
    const text = contentField ? contentField.value || '' : '';

    console.log('[sources] build payload fields', {
      hasContentField: Boolean(contentField),
      hasLanguageField: Boolean(languageField),
      hasHidden: Boolean(sourceHidden),
      hasText: Boolean(sourceText),
    });

    // Get original chapter JSON to preserve children
    const originalJsonInput = editForm.querySelector('.original-chapter-json');
    let originalData = {};
    if (originalJsonInput) {
      try {
        originalData = JSON.parse(originalJsonInput.value);
      } catch (err) {
        console.warn('Failed to parse original chapter JSON:', err);
      }
    }

    // Build payload preserving children from original
    const payload = {
      title,
      content: originalData.content || text,
    };

    // If we have original content with children, merge our text into it
    if (originalData.content && Array.isArray(originalData.content)) {
      const textParts = [];
      const children = [];
      
      // Separate text and children from original
      for (const item of originalData.content) {
        if (typeof item === 'string') {
          textParts.push(item);
        } else if (typeof item === 'object') {
          children.push(item);
        }
      }
      
      // Build new content with updated text and preserved children
      payload.content = [];
      if (text) {
        payload.content.push(text);
      }
      payload.content.push(...children);
    } else {
      // No children, just use text
      payload.content = text;
    }

    if (language) {
      payload.language = language;
    }
    // Always include source (empty string will clear it server-side)
    payload.source = sourceValue;

    payloadInput.value = JSON.stringify(payload);
  }

  function ensureCss(id, href) {
    if (document.getElementById(id)) return;
    const link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function loadScriptOnce(id, src) {
    return new Promise((resolve, reject) => {
      if (document.getElementById(id)) {
        resolve();
        return;
      }
      const script = document.createElement('script');
      script.id = id;
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  // JSON Editor save functionality
  document.addEventListener('click', (e) => {
    if (e.target.id === 'json-editor-save') {
      saveJsonEditor();
    }
  });

  async function saveJsonEditor() {
    const statusEl = document.getElementById('json-editor-status');
    const noteId = document.getElementById('editor')?.dataset.noteId;
    
    if (!noteId) return;
    
    // Get value from CodeMirror if available, otherwise from textarea
    let jsonValue;
    if (jsonCodeMirrorInstance) {
      jsonValue = jsonCodeMirrorInstance.getValue();
    } else {
      const textarea = document.getElementById('json-editor-textarea');
      if (!textarea) return;
      jsonValue = textarea.value;
    }
    
    try {
      const noteData = JSON.parse(jsonValue);
      
      statusEl.textContent = 'Saving...';
      statusEl.className = 'json-editor-status';
      
      const response = await fetch(`/api/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: noteData.title,
          tags: noteData.tags,
          chapters: noteData.chapters
        })
      });
      
      if (response.ok) {
        statusEl.textContent = 'Saved successfully!';
        statusEl.className = 'json-editor-status success';
        setTimeout(() => {
          statusEl.textContent = '';
        }, 3000);
      } else {
        throw new Error('Save failed');
      }
    } catch (err) {
      statusEl.textContent = `Error: ${err.message}`;
      statusEl.className = 'json-editor-status error';
    }
  }

  // Reapply editor mode after HTMX swaps
  document.body.addEventListener('htmx:afterSwap', () => {
    const mode = localStorage.getItem('editor-mode') || 'graphical';
    applyEditorMode(mode);
    
    // Initialize read-only code block displays
    initializeCodeBlockDisplays();
    
    // Initialize math block rendering (with slight delay to ensure KaTeX is loaded)
    setTimeout(() => initializeMathBlocks(), 100);

    // Initialize token inputs (e.g., Sources chips)
    initializeTokenInputs();
  });

  // Persist collapsed state per pane across reloads
  const paneKeys = {
    'note-list': '--notes-col',
    'chapter-list': null,
  };

  function applyCollapsedStateFromStorage() {
    const isNarrow = window.matchMedia('(max-width: 960px)').matches;
    Object.keys(paneKeys).forEach((paneId) => {
      // In narrow mode, notes list starts collapsed
      const collapsed = isNarrow && paneId === 'note-list'
        ? true
        : localStorage.getItem(`pane:${paneId}:collapsed`) === '1';
      const el = document.getElementById(paneId);
      if (!el) return;
      el.classList.toggle('collapsed', collapsed);
      const content = el.querySelector('.pane-content');
      if (content) content.style.display = collapsed ? 'none' : '';
      const colVar = paneKeys[paneId];
      if (colVar && !isNarrow) {
        root.style.setProperty(colVar, collapsed ? '48px' : '260px');
      }
    });
  }

  applyCollapsedStateFromStorage();

  // Initialize read-only displays on initial page load
  initializeCodeBlockDisplays();
  setTimeout(() => initializeMathBlocks(), 100);
  // Initialize token inputs on initial load
  initializeTokenInputs();
  // Initialize drag and drop
  initDragAndDrop();
  // Initialize add block handlers
    // CSS-only add button module active; no JS initialization required

  // Dropdown positioning for narrow mode
  function updateDropdownPosition() {
    const noteList = document.getElementById('note-list');
    const header = document.querySelector('.pane.editor .pane-header');
    const mainContainer = document.querySelector('.main-container');
    
    if (!noteList || !header) return;
    
    // Don't position dropdown when no note is open
    if (mainContainer && mainContainer.classList.contains('no-note-open')) {
      noteList.style.top = '';
      return;
    }
    
    const isNarrow = window.matchMedia('(max-width: 960px)').matches;
    if (!isNarrow) {
      noteList.style.top = '';
      return;
    }
    
    // Position dropdown below the sticky header
    const headerRect = header.getBoundingClientRect();
    noteList.style.top = `${headerRect.bottom}px`;
  }

  // Sticky header detection for editor pane
  function initStickyHeader() {
    const editorPane = document.querySelector('.pane.editor');
    if (!editorPane) return;
    
    const header = editorPane.querySelector('.pane-header');
    if (!header) return;

    // Create a sentinel element just above the header
    const sentinel = document.createElement('div');
    sentinel.style.position = 'absolute';
    sentinel.style.top = '0';
    sentinel.style.height = '1px';
    sentinel.style.width = '1px';
    sentinel.style.pointerEvents = 'none';
    editorPane.style.position = 'relative';
    editorPane.insertBefore(sentinel, header);

    const observer = new IntersectionObserver(
      ([entry]) => {
        header.classList.toggle('stuck', !entry.isIntersecting);
        updateDropdownPosition();
      },
      { threshold: [0], rootMargin: '0px' }
    );

    observer.observe(sentinel);
  }

  // Update dropdown position on scroll
  let scrollTicking = false;
  window.addEventListener('scroll', () => {
    if (!scrollTicking) {
      requestAnimationFrame(() => {
        updateDropdownPosition();
        scrollTicking = false;
      });
      scrollTicking = true;
    }
  }, { passive: true });
  
  window.addEventListener('resize', updateDropdownPosition);
  window.addEventListener('load', updateDropdownPosition);

  initStickyHeader();
  // Initial dropdown position (wait for DOM to settle)
  setTimeout(updateDropdownPosition, 200);

  // Re-initialize sticky header after HTMX swaps
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target.id === 'editor' || e.detail.target.closest('#editor')) {
      setTimeout(() => {
        initStickyHeader();
        updateDropdownPosition();
      }, 50);
    }
  });

  // Update position after any HTMX request completes
  document.body.addEventListener('htmx:afterOnLoad', () => {
    setTimeout(updateDropdownPosition, 50);
  });

  document.body.addEventListener('click', (e) => {
    const target = e.target.closest('[data-toggle-pane]');
    if (!target) return;
    const paneId = target.getAttribute('data-toggle-pane');
    const el = document.getElementById(paneId);
    if (!el) return;

    const content = el.querySelector('.pane-content');
    const colVar = el.getAttribute('data-col-var');
    const isNarrow = window.matchMedia('(max-width: 960px)').matches;

    const collapsed = el.classList.toggle('collapsed');
    if (content) content.style.display = collapsed ? 'none' : '';
    if (colVar && !isNarrow) {
      root.style.setProperty(colVar, collapsed ? '48px' : '260px');
    }
    // Update toggle button state (for narrow mode dropdown indicator)
    if (isNarrow && paneId === 'note-list') {
      target.classList.toggle('pane-open', !collapsed);
      // Toggle body class to show/hide add note button
      document.body.classList.toggle('notes-dropdown-open', !collapsed);
      // Update dropdown position after toggle
      setTimeout(updateDropdownPosition, 10);
    }
    // Only persist in wide mode — narrow always starts collapsed
    if (!isNarrow) {
      localStorage.setItem(`pane:${paneId}:collapsed`, collapsed ? '1' : '0');
    }
  });

  // In narrow mode, auto-collapse note list when a note is selected
  document.body.addEventListener('click', (e) => {
    const isNarrow = window.matchMedia('(max-width: 960px)').matches;
    if (!isNarrow) return;
    const item = e.target.closest('#note-list .item');
    if (!item) return;
    // Small delay to let HTMX fire first
    setTimeout(() => {
      const noteList = document.getElementById('note-list');
      if (noteList && !noteList.classList.contains('collapsed')) {
        noteList.classList.add('collapsed');
        const content = noteList.querySelector('.pane-content');
        if (content) content.style.display = 'none';
        // Reset toggle button arrow direction and body class
        const toggleBtn = document.querySelector('.narrow-notes-toggle');
        if (toggleBtn) toggleBtn.classList.remove('pane-open');
        document.body.classList.remove('notes-dropdown-open');
      }
    }, 150);
  });

  // Handle Enter key in chapter edit forms
  document.body.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      const form = e.target.closest('.chapter-edit-form');
      if (form) {
        e.preventDefault();
        // Only block submit on invalid JSON in JSON editor mode
        const jsonTextarea = form.querySelector('textarea.chapter-json-editor');
        if (jsonTextarea) {
          try {
            JSON.parse(jsonTextarea.value);
          } catch (err) {
            console.warn('Submit blocked: JSON parse error', err?.message || err);
            return;
          }
        }
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.click();
      }
    }
  });

  // Editor initialization and UI reset after HTMX swaps
  // Before swapping content, close any editor attached to the old container
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    // Find and close all existing editors in the document
    document.querySelectorAll('.chapter-edit-mode').forEach((editForm) => {
      if (editForm._editorInstance) {
        try {
          editForm._editorInstance.unmount();
          editForm._editorInstance = null;
        } catch (err) {
          console.warn('Editor unmount on beforeSwap failed:', err);
        }
      }
    });
    // Also remove any orphaned CodeMirror wrappers
    document.querySelectorAll('.CodeMirror').forEach((wrapper) => {
      try {
        if (wrapper.parentNode) {
          wrapper.parentNode.removeChild(wrapper);
        }
      } catch (err) {
        console.warn('Orphaned CodeMirror cleanup failed:', err);
      }
    });
  });

  document.body.addEventListener('htmx:afterSwap', async () => {
    console.log('[htmx:afterSwap] Event fired');
    document.querySelectorAll('.add-zone').forEach((el) => el.classList.remove('show'));
    applyCollapsedStateFromStorage();

    // Initialize editor for chapter edit form
    const editForm = document.querySelector('.chapter-edit-mode');
    console.log('[htmx:afterSwap] editForm found:', editForm);
    const hasTextarea = editForm?.querySelector('textarea');
    console.log('[htmx:afterSwap] hasTextarea:', hasTextarea);
    const editorType = editForm?.dataset.editor || 'textarea';
    console.log('[htmx:afterSwap] editorType:', editorType);
    
    // Skip editor initialization if no textarea (e.g., for chapter blocks)
    if (editForm && hasTextarea) {
      console.log('[htmx:afterSwap] Starting editor initialization...');
      const editorOptions = {
        mode: editForm.dataset.codemirrorMode,
      };
      console.log('[htmx:afterSwap] editorOptions:', editorOptions);
      
      try {
        console.log('[editor] Initializing editor:', { editorType, hasTextarea, editForm });
        const EditorClass = await loadEditorClass(editorType);
        console.log('[editor] EditorClass loaded:', EditorClass);
        const editor = new EditorClass(editForm, editorOptions);
        console.log('[editor] Editor instance created, mounting...');
        await editor.mount();
        console.log('[editor] Editor mounted successfully');
        // Attach editor instance to the container so it's tied to that element's lifecycle
        editForm._editorInstance = editor;

        editor.on('submit', () => {
          const form = editForm.querySelector('form');
          const textarea = editForm.querySelector('textarea');
          if (textarea) {
            textarea.value = editor.getValue();
          }
          if (form) {
            // Commit token inputs (e.g., sources) before building payload
            synchronizeAllTokenInputs(form);
            buildChapterJsonPayload(form);
          }
          if (form) {
            htmx.ajax('POST', form.getAttribute('hx-post'), {
              values: new FormData(form),
              target: form.getAttribute('hx-target') || 'body',
              swap: form.getAttribute('hx-swap') || 'innerHTML',
            });
          }
        });

        // Listen for language changes in code editors
        const languageSelect = editForm.querySelector('select[name="language"]');
        if (languageSelect && (editorType === 'codemirror' || editorType === 'code-block')) {
          languageSelect.addEventListener('change', async (e) => {
            const newLang = e.target.value;
            const modeMap = {
              'python': 'python',
              'javascript': 'javascript',
              'typescript': 'javascript',
              'go': 'go',
              'rust': 'rust',
              'java': 'clike'
            };
            const mimeMap = {
              'python': 'text/x-python',
              'javascript': 'text/javascript',
              'typescript': 'text/typescript',
              'go': 'text/x-go',
              'rust': 'text/x-rustsrc',
              'java': 'text/x-java'
            };
            
            const mode = modeMap[newLang] || 'javascript';
            const mime = mimeMap[newLang] || 'text/javascript';
            
            // Load the language mode if needed
            const modeFiles = {
              'python': '/static/vendor/codemirror/python.js',
              'javascript': '/static/vendor/codemirror/javascript.js',
              'go': '/static/vendor/codemirror/go.js',
              'rust': '/static/vendor/codemirror/rust.js',
              'java': '/static/vendor/codemirror/java.js',
            };
            
            const scriptId = `cm-mode-${mode}`;
            if (!document.getElementById(scriptId) && modeFiles[mode]) {
              await new Promise((resolve) => {
                const script = document.createElement('script');
                script.id = scriptId;
                script.src = modeFiles[mode];
                script.onload = resolve;
                document.head.appendChild(script);
              });
            }
            
            // Update the editor mode
            if (editor._editorInstance?.editor) {
              editor._editorInstance.editor.setOption('mode', mime);
            } else if (editor.editor) {
              editor.editor.setOption('mode', mime);
            }
          });
        }

        // Click-outside auto-save removed per request; rely on explicit Save/Cancel.
      } catch (err) {
        console.error('[editor] Failed to initialize editor:', err);
        console.error('[editor] Stack trace:', err.stack);
      }
    }

    // Focus textarea only if using the plain textarea editor
    if (editForm && editorType === 'textarea') {
      const textarea = editForm.querySelector('textarea');
      if (textarea) {
        textarea.focus();
        textarea.setSelectionRange(0, 0);
      }
    }

    // Re-initialize read-only displays after swap
    initializeCodeBlockDisplays();
    setTimeout(() => initializeMathBlocks(), 100);
    // Initialize token inputs for newly inserted forms
    initializeTokenInputs();
    // Re-initialize drag and drop after HTMX swap
    initDragAndDrop();

    // Initialize settings pane controls if present
    const settingsOverlay = document.getElementById('note-settings');
    if (settingsOverlay) {
      // Initialize editor mode radios from localStorage
      const mode = localStorage.getItem('editor-mode') || 'graphical';
      const radio = settingsOverlay.querySelector(`input[name="editor-mode-setting"][value="${mode}"]`);
      if (radio) radio.checked = true;

      // Initialize text language select
      const textSel = settingsOverlay.querySelector('#text-language');
      if (textSel) {
        const storedTextLang = localStorage.getItem('text-language') || 'en';
        textSel.value = storedTextLang;
      }
    }

    // Apply text language to any open paragraph editors
    (function applyTextLangOnSwap(){
      const lang = localStorage.getItem('text-language') || 'en';
      document.querySelectorAll('.chapter-edit-mode').forEach((editForm) => {
        const isParagraph = editForm.dataset.chapterType === 'paragraph';
        if (!isParagraph) return;
        const textarea = editForm.querySelector('textarea.chapter-content-input');
        if (textarea) {
          textarea.setAttribute('lang', lang);
          textarea.setAttribute('spellcheck', 'true');
          textarea.setAttribute('autocapitalize', 'sentences');
          textarea.setAttribute('autocomplete', 'on');
          textarea.setAttribute('autocorrect', 'on');
        }
      });
    })();
  });

  document.body.addEventListener('submit', (e) => {
    // Generic confirm handler for forms with data-confirm (capture early)
    const confirmForm = e.target.closest('form[data-confirm]');
    if (confirmForm) {
      const msg = confirmForm.getAttribute('data-confirm') || 'Are you sure?';
      if (!window.confirm(msg)) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
    }

    const form = e.target.closest('.chapter-edit-form');
    if (!form) return;
    synchronizeAllTokenInputs(form);
    buildChapterJsonPayload(form);
  }, true);

  // Settings pane interactions
  // Close the note settings overlay when server triggers it (on delete)
  document.body.addEventListener('close-note-settings', () => {
    const overlay = document.getElementById('note-settings');
    if (overlay) overlay.remove();
  });

  // Close settings pane
  document.body.addEventListener('click', (e) => {
    const closeBtn = e.target.closest('[data-close-settings]');
    if (!closeBtn) return;
    const overlay = closeBtn.closest('.note-settings-overlay');
    if (overlay) overlay.remove();
  });

  // Apply editor mode from settings (graphical/json)
  document.body.addEventListener('change', (e) => {
    const radio = e.target.closest('input[name="editor-mode-setting"]');
    if (!radio) return;
    const mode = radio.value;
    localStorage.setItem('editor-mode', mode);
    // Apply immediately
    try {
      if (typeof applyEditorMode === 'function') {
        applyEditorMode(mode);
      }
    } catch {}
  });

  // Persist and apply text language for paragraph editors
  function applyTextLanguageToEditors() {
    const lang = localStorage.getItem('text-language') || 'en';
    document.querySelectorAll('.chapter-edit-mode').forEach((editForm) => {
      const isParagraph = editForm.dataset.chapterType === 'paragraph';
      if (!isParagraph) return;
      const textarea = editForm.querySelector('textarea.chapter-content-input');
      if (textarea) {
        textarea.setAttribute('lang', lang);
        textarea.setAttribute('spellcheck', 'true');
        textarea.setAttribute('autocapitalize', 'sentences');
        textarea.setAttribute('autocomplete', 'on');
        textarea.setAttribute('autocorrect', 'on');
      }
    });
  }

  document.body.addEventListener('change', (e) => {
    const select = e.target.closest('#text-language');
    if (!select) return;
    localStorage.setItem('text-language', select.value);
    applyTextLanguageToEditors();
  });

  // Handle chapter click with mode detection
  document.body.addEventListener('click', (e) => {
    const chapterView = e.target.closest('.chapter-click');
    if (!chapterView) return;
    
    const noteId = chapterView.dataset.noteId;
    const chapterId = chapterView.dataset.chapterId;
    const editorMode = localStorage.getItem('editor-mode') || 'graphical';
    const useJsonEditor = editorMode === 'json';
    
    const url = `/notes/${noteId}/chapters/${chapterId}/edit?mode=${useJsonEditor ? 'json' : 'graphical'}`;
    const target = `#chapter-${chapterId}`;
    
    if (window.htmx) {
      window.htmx.ajax('GET', url, {
        target: target,
        swap: 'innerHTML'
      });
    }
  });

  const INSERT_DELAY = 800; // ms
  const PERSIST_DELAY = 2500; // ms
  const timers = new WeakMap();
  const persistTimers = new WeakMap();

  function hideAllAddButtons() {
    document.querySelectorAll('.add-zone.show').forEach((el) => {
      el.classList.remove('show');
      clearPersistTimer(el);
    });
    document.querySelectorAll('.chapter-section').forEach((section) => {
      clearPersistTimer(section);
    });
  }

  function startTimer(el, showFn) {
    if (timers.has(el)) return;
    const t = setTimeout(() => {
      hideAllAddButtons();
      showFn();
      timers.delete(el);
    }, INSERT_DELAY);
    timers.set(el, t);
  }

  function clearTimer(el) {
    const t = timers.get(el);
    if (t) {
      clearTimeout(t);
      timers.delete(el);
    }
  }

  function startPersistTimer(el, hideFn) {
    const existing = persistTimers.get(el);
    if (existing) {
      clearTimeout(existing);
    }
    const t = setTimeout(() => {
      hideFn();
      persistTimers.delete(el);
    }, PERSIST_DELAY);
    persistTimers.set(el, t);
  }

  function clearPersistTimer(el) {
    const t = persistTimers.get(el);
    if (t) {
      clearTimeout(t);
      persistTimers.delete(el);
    }
  }

  document.body.addEventListener('mouseover', (e) => {
    const section = e.target.closest('.chapter-section');
    if (section) {
      const from = e.relatedTarget;
      if (!(from && section.contains(from))) {
        const childZone = section.querySelector('.add-zone.add-child');
        if (childZone) {
          clearPersistTimer(section);
          startTimer(section, () => childZone.classList.add('show'));
        }
      }
    }

    const zone = e.target.closest('.add-zone');
    if (zone && !zone.classList.contains('add-child')) {
      const from = e.relatedTarget;
      if (!(from && zone.contains(from))) {
        clearPersistTimer(zone);
        startTimer(zone, () => zone.classList.add('show'));
      }
    }
  });

  document.body.addEventListener('mouseout', (e) => {
    const section = e.target.closest('.chapter-section');
    if (section) {
      const to = e.relatedTarget;
      if (!(to && section.contains(to))) {
        clearTimer(section);
        const childZone = section.querySelector('.add-zone.add-child');
        if (childZone && childZone.classList.contains('show')) {
          startPersistTimer(section, () => childZone.classList.remove('show'));
        }
      }
    }

    const zone = e.target.closest('.add-zone');
    if (zone && !zone.classList.contains('add-child')) {
      const to = e.relatedTarget;
      if (!(to && zone.contains(to))) {
        clearTimer(zone);
        if (zone.classList.contains('show')) {
          startPersistTimer(zone, () => zone.classList.remove('show'));
        }
      }
    }
  });

  // Ensure all add zones start hidden on initial load
  document.querySelectorAll('.add-zone').forEach((el) => el.classList.remove('show'));

  // NOTE: Drag-and-drop for chapters is now handled by drag-drop.js module
  // The old handlers here have been removed to avoid conflicts.

  // Accessibility: simple keyboard shortcut capture and logging
  function _normalizeKeyEvent(e) {
    // Handle modifier combos first
    if (e.key === 'Enter' && e.shiftKey) return 'shift enter';
    // Map common keys to human-friendly strings used in accessibility.cfg
    const map = {
      'ArrowDown': 'down arrow',
      'ArrowUp': 'up arrow',
      'ArrowRight': 'right arrow',
      'ArrowLeft': 'left arrow',
      'Escape': 'esc',
      'Enter': 'enter',
      'Backspace': 'back space',
    };
    if (map[e.key]) return map[e.key];
    // Single character keys (letters, digits)
    if (e.key && e.key.length === 1) return e.key.toLowerCase();
    // Fallback to key value
    return e.key || String(e.which || 'unknown');
  }

  const _accessibilityMap = (window.WISENOTES_ACCESSIBILITY && typeof window.WISENOTES_ACCESSIBILITY === 'object') ? window.WISENOTES_ACCESSIBILITY : {};
  // Invert mapping for quick lookup: keyString -> actionName
  const _keyToAction = {};
  Object.keys(_accessibilityMap).forEach((action) => {
    const v = String(_accessibilityMap[action]).trim().toLowerCase();
    if (v) _keyToAction[v] = action;
  });

  document.addEventListener('keydown', (e) => {
    try {
      const keyStr = _normalizeKeyEvent(e);
      const action = _keyToAction[keyStr];
      if (action) {
        console.log('[accessibility] key pressed', { key: keyStr, action });
      } else {
        console.log('[accessibility] key pressed (unmapped)', { key: keyStr });
      }
    } catch (err) {
      console.warn('Accessibility key handler error', err);
    }
  });
});

// Media upload and gallery handling
document.addEventListener('DOMContentLoaded', () => {
  initMediaHandlers();
});

document.body.addEventListener('htmx:afterSwap', () => {
  initMediaHandlers();
});

function initMediaHandlers() {
  // No longer init inline handlers - all media handling is via HTMX panel
}


function loadMediaBrowserGallery() {
  if (!currentMediaBrowserNote) return;

  const gallery = document.getElementById('media-browser-gallery');
  if (!gallery) return;

  gallery.innerHTML = '<p style="grid-column: 1 / -1; color: #999; text-align: center;">Loading...</p>';

  fetch(`/api/notes/${currentMediaBrowserNote}/media/list`)
    .then(r => r.json())
    .then(data => {
      gallery.innerHTML = '';
      if (data.media.length === 0) {
        gallery.innerHTML = '<p style="grid-column: 1 / -1; color: #999; text-align: center;">No media uploaded yet. Upload some images above.</p>';
        return;
      }

      data.media.forEach(filename => {
        const imgUrl = `/api/notes/${currentMediaBrowserNote}/media/${filename}`;
        const item = document.createElement('div');
        item.style.position = 'relative';
        item.style.cursor = 'pointer';
        item.style.borderRadius = '4px';
        item.style.overflow = 'hidden';
        item.style.border = '2px solid #e0e0e0';
        item.style.transition = 'all 0.2s';
        
        item.innerHTML = `
          <img src="${imgUrl}" 
               style="width: 100%; aspect-ratio: 1; object-fit: cover;"
               title="${filename}"
               alt="${filename}"
               data-filename="${filename}">
          <button type="button" class="media-delete" 
                  style="position: absolute; top: 4px; right: 4px; background: #e53e3e; color: white; border: none; width: 24px; height: 24px; border-radius: 50%; cursor: pointer; font-size: 16px; font-weight: bold; display: none;">
            ×
          </button>
        `;

        // Show delete button on hover
        item.addEventListener('mouseenter', () => {
          item.querySelector('.media-delete').style.display = 'block';
          item.style.opacity = '0.8';
        });
        item.addEventListener('mouseleave', () => {
          item.querySelector('.media-delete').style.display = 'none';
          item.style.opacity = '1';
        });

        // Click image to select
        item.querySelector('img').addEventListener('click', () => {
          selectMedia(imgUrl);
        });

        // Delete button
        item.querySelector('.media-delete').addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (confirm(`Delete ${filename}?`)) {
            fetch(`/api/notes/${currentMediaBrowserNote}/media/${filename}`, { method: 'DELETE' })
              .then(r => r.json())
              .then(() => {
                item.remove();
                loadMediaBrowserGallery();
              })
              .catch(err => alert('Delete failed: ' + err.message));
          }
        });

        gallery.appendChild(item);
      });
    })
    .catch(err => {
      gallery.innerHTML = `<p style="grid-column: 1 / -1; color: #e53e3e; text-align: center;">Failed to load media: ${err.message}</p>`;
      console.error('Failed to load media gallery', err);
    });
}

function setupMediaBrowserUpload() {
  const dropZone = document.getElementById('media-upload-drop-zone');
  const fileInput = document.getElementById('media-upload-input');
  
  if (!dropZone || !fileInput) return;

  // Click to upload
  dropZone.addEventListener('click', () => fileInput.click());

  // Drag and drop
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.style.background = '#f0f0f0';
    dropZone.style.borderColor = '#999';
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.style.background = '';
    dropZone.style.borderColor = '#ccc';
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.style.background = '';
    dropZone.style.borderColor = '#ccc';
    const files = e.dataTransfer.files;
    uploadMediaFiles(Array.from(files));
  });

  // File input change
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      uploadMediaFiles(Array.from(e.target.files));
    }
  });
}

function uploadMediaFiles(files) {
  if (!currentMediaBrowserNote) return;

  const uploadProgress = document.getElementById('upload-progress');
  const progressBar = document.getElementById('progress-bar');

  uploadProgress.style.display = 'block';
  progressBar.style.width = '0%';

  let uploaded = 0;
  let total = files.length;

  files.forEach((file, index) => {
    const formData = new FormData();
    formData.append('file', file);

    fetch(`/api/notes/${currentMediaBrowserNote}/media/upload`, {
      method: 'POST',
      body: formData
    })
      .then(r => r.json())
      .then(data => {
        uploaded++;
        progressBar.style.width = ((uploaded / total) * 100) + '%';
        if (uploaded === total) {
          setTimeout(() => {
            uploadProgress.style.display = 'none';
            loadMediaBrowserGallery();
          }, 500);
        }
      })
      .catch(err => {
        alert(`Upload failed for ${file.name}: ${err.message}`);
        console.error('Upload error', err);
      });
  });
}


