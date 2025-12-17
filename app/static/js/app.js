/**
 * Dynamically load and instantiate editor class
 */
async function loadEditorClass(editorType) {
  switch (editorType) {
    case 'codemirror': {
      const { CodeMirrorEditor } = await import('./editors/codemirror-editor.js');
      return CodeMirrorEditor;
    }
    case 'textarea':
    default: {
      const { TextareaEditor } = await import('./editors/textarea-editor.js');
      return TextareaEditor;
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
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
            'rust': 'text/x-rustsrc'
          };

          const modeMap = {
            'python': 'python',
            'javascript': 'javascript',
            'typescript': 'javascript',
            'go': 'go',
            'rust': 'rust'
          };

          const mode = modeMap[language] || 'javascript';
          const mime = mimeMap[language] || 'text/javascript';

          // Load language mode if needed
          const modeFiles = {
            'python': '/static/vendor/codemirror/python.js',
            'javascript': '/static/vendor/codemirror/javascript.js',
            'go': '/static/vendor/codemirror/go.js',
            'rust': '/static/vendor/codemirror/rust.js',
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
    const contentField = editForm.querySelector('[data-editor-target]');
    const languageField = editForm.querySelector('select[name="language"], input[name="language"]');
    const language = languageField ? languageField.value || '' : '';
    const text = contentField ? contentField.value || '' : '';

    const payload = {
      title,
      content: text,
    };

    if (language) {
      payload.language = language;
    }

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
  });

  // Persist collapsed state per pane across reloads
  const paneKeys = {
    'note-list': '--notes-col',
    'chapter-list': null,
  };

  function applyCollapsedStateFromStorage() {
    Object.keys(paneKeys).forEach((paneId) => {
      const collapsed = localStorage.getItem(`pane:${paneId}:collapsed`) === '1';
      const el = document.getElementById(paneId);
      if (!el) return;
      el.classList.toggle('collapsed', collapsed);
      const content = el.querySelector('.pane-content');
      if (content) content.style.display = collapsed ? 'none' : '';
      const colVar = paneKeys[paneId];
      if (colVar) {
        root.style.setProperty(colVar, collapsed ? '48px' : '260px');
      }
    });
  }

  applyCollapsedStateFromStorage();

  document.body.addEventListener('click', (e) => {
    const target = e.target.closest('[data-toggle-pane]');
    if (!target) return;
    const paneId = target.getAttribute('data-toggle-pane');
    const el = document.getElementById(paneId);
    if (!el) return;

    const content = el.querySelector('.pane-content');
    const colVar = el.getAttribute('data-col-var');

    const collapsed = el.classList.toggle('collapsed');
    if (content) content.style.display = collapsed ? 'none' : '';
    if (colVar) {
      root.style.setProperty(colVar, collapsed ? '48px' : '260px');
    }
    // Save state
    localStorage.setItem(`pane:${paneId}:collapsed`, collapsed ? '1' : '0');
  });

  // Handle Enter key in chapter edit forms
  document.body.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const form = e.target.closest('.chapter-edit-form');
      if (form) {
        e.preventDefault();
        // Block submit on invalid JSON
        const textarea = form.querySelector('textarea');
        if (textarea) {
          try {
            JSON.parse(textarea.value);
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
    document.querySelectorAll('.add-zone').forEach((el) => el.classList.remove('show'));
    applyCollapsedStateFromStorage();

    // Initialize editor for chapter edit form
    const editForm = document.querySelector('.chapter-edit-mode');
    const editorType = editForm?.dataset.editor || 'textarea';
    const editorOptions = {
      mode: editForm?.dataset.codemirrorMode,
    };
    
    if (editForm) {
      try {

        const EditorClass = await loadEditorClass(editorType);
        const editor = new EditorClass(editForm, editorOptions);
        await editor.mount();
        // Attach editor instance to the container so it's tied to that element's lifecycle
        editForm._editorInstance = editor;

        editor.on('submit', () => {
          const form = editForm.querySelector('form');
          const textarea = editForm.querySelector('textarea');
          if (textarea) {
            textarea.value = editor.getValue();
          }
          if (form) {
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
        if (languageSelect && editorType === 'codemirror') {
          languageSelect.addEventListener('change', async (e) => {
            const newLang = e.target.value;
            const modeMap = {
              'python': 'python',
              'javascript': 'javascript',
              'typescript': 'javascript',
              'go': 'go',
              'rust': 'rust'
            };
            const mimeMap = {
              'python': 'text/x-python',
              'javascript': 'text/javascript',
              'typescript': 'text/typescript',
              'go': 'text/x-go',
              'rust': 'text/x-rustsrc'
            };
            
            const mode = modeMap[newLang] || 'javascript';
            const mime = mimeMap[newLang] || 'text/javascript';
            
            // Load the language mode if needed
            const modeFiles = {
              'python': '/static/vendor/codemirror/python.js',
              'javascript': '/static/vendor/codemirror/javascript.js',
              'go': '/static/vendor/codemirror/go.js',
              'rust': '/static/vendor/codemirror/rust.js',
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
        console.error('Failed to initialize editor:', err);
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
  });

  document.body.addEventListener('submit', (e) => {
    const form = e.target.closest('.chapter-edit-form');
    if (!form) return;
    buildChapterJsonPayload(form);
  }, true);

  // Handle chapter click with mode detection
  document.body.addEventListener('click', (e) => {
    const chapterView = e.target.closest('.chapter-click');
    if (!chapterView) return;
    
    const noteId = chapterView.dataset.noteId;
    const chapterId = chapterView.dataset.chapterId;
    const editorMode = localStorage.getItem('editor-mode') || 'graphical';
    const useJsonEditor = editorMode === 'graphical'; // "JSON Editor" mode
    
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

  document.body.addEventListener('dragstart', (e) => {
    const item = e.target.closest('.chapter-item');
    if (!item) return;
    if (!e.dataTransfer) return;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('chapter-id', item.dataset.chapterId);
  });

  document.body.addEventListener('dragover', (e) => {
    const item = e.target.closest('.chapter-item');
    if (!item) return;
    if (!e.dataTransfer) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    item.classList.add('drag-over');
  });

  document.body.addEventListener('dragleave', (e) => {
    const item = e.target.closest('.chapter-item');
    if (!item) return;
    item.classList.remove('drag-over');
  });

  document.body.addEventListener('drop', (e) => {
    const item = e.target.closest('.chapter-item');
    if (!item) return;
    if (!e.dataTransfer) return;
    e.preventDefault();

    const chapterId = e.dataTransfer.getData('chapter-id');
    const parentId = item.dataset.chapterId;
    const noteId = document.querySelector('[data-note-id]')?.dataset.noteId;
    item.classList.remove('drag-over');

    if (!noteId || !chapterId || chapterId === parentId) return;

    fetch(`/notes/${noteId}/chapters/${chapterId}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `parent_id=${encodeURIComponent(parentId)}`
    }).then(() => {
      if (window.htmx) {
        window.htmx.ajax('GET', `/notes/${noteId}`, 'body');
      }
    });
  });
});
