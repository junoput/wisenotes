document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;

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
  });

  // Handle Enter key in chapter edit forms
  document.body.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      const form = e.target.closest('.chapter-edit-form');
      if (form) {
        e.preventDefault();
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.click();
      }
    }
  });

  // Delayed hover reveal for add zones and chapter child overlays
  const INSERT_DELAY = 800; // ms
  const PERSIST_DELAY = 2500; // ms - how long to keep button visible after hover ends
  const timers = new WeakMap();
  const persistTimers = new WeakMap();

  function hideAllAddButtons() {
    // Hide all add zone buttons
    document.querySelectorAll('.add-zone.show').forEach((el) => {
      el.classList.remove('show');
      clearPersistTimer(el);
    });
    // Clear all persist timers
    document.querySelectorAll('.chapter-section').forEach((section) => {
      clearPersistTimer(section);
    });
  }

  function startTimer(el, showFn) {
    if (timers.has(el)) return;
    const t = setTimeout(() => {
      hideAllAddButtons(); // Hide any previously visible buttons
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
    // Child overlay: trigger when hovering the chapter section
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

    // Between/top/bottom/empty zones: trigger when hovering the zone itself
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

  // Ensure all add zones start hidden on initial load and after swaps
  document.body.addEventListener('htmx:afterSwap', () => {
    document.querySelectorAll('.add-zone').forEach((el) => el.classList.remove('show'));
  });
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
