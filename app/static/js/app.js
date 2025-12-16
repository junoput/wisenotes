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
    // Always use codemirror for consistency
    const editorType = 'codemirror';
    
    if (editForm) {
      try {

        const EditorClass = await loadEditorClass(editorType);
        const editor = new EditorClass(editForm);
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
            htmx.ajax('POST', form.getAttribute('hx-post'), {
              values: new FormData(form),
              target: form.getAttribute('hx-target') || 'body',
              swap: form.getAttribute('hx-swap') || 'innerHTML',
            });
          }
        });

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
