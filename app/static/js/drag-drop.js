/**
 * Drag and drop with ghost block visual.
 * When dragging, the block becomes a ghost (semi-transparent).
 * The ghost snaps to block positions as cursor moves.
 * On drop, the block moves to the target position and becomes solid again.
 */

console.log('[drag-drop.js] module loaded - ghost block mode');

let draggedEl = null;
let targetBlockId = null; // Track which block is the target

function onDragStart(e) {
  draggedEl = e.target.closest('.chapter-section');
  if (!draggedEl) {
    e.preventDefault();
    return;
  }

  const draggedType = draggedEl.dataset.chapterType || 'chapter';
  console.log('[drag-drop] dragstart', {
    id: draggedEl.dataset.chapterId,
    type: draggedType,
  });
  
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', draggedEl.dataset.chapterId);

  targetBlockId = null;

  // Make block appear as ghost
  requestAnimationFrame(() => {
    draggedEl.classList.add('dragging');
    draggedEl.style.opacity = '0.4';
    draggedEl.style.pointerEvents = 'none';
  });
}

function onDragEnd() {
  if (draggedEl) {
    draggedEl.classList.remove('dragging');
    draggedEl.style.opacity = '1';
    draggedEl.style.pointerEvents = 'auto';
  }
  draggedEl = null;
  targetBlockId = null;
}

function onDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  if (!draggedEl) return;

  const target = e.currentTarget;
  if (target === draggedEl) return;
  if (draggedEl.contains(target)) return;

  const draggedType = draggedEl.dataset.chapterType || 'chapter';
  const targetParentId = target.dataset?.parentId || '';
  
  // Prevent non-chapter blocks from being positioned at root
  if (draggedType !== 'chapter' && targetParentId === '') {
    e.dataTransfer.dropEffect = 'none';
    return;
  }

  e.dataTransfer.dropEffect = 'move';

  // Get target's parent chapter and position
  const targetId = target.dataset?.chapterId;
  
  // Update target tracking and move ghost block
  if (targetId !== targetBlockId) {
    targetBlockId = targetId;
    console.log('[drag-drop] hovering over block', { targetId, targetParentId });
    // Position ghost by inserting after target (no highlight)
    if (target.parentNode) {
      target.parentNode.insertBefore(draggedEl, target.nextSibling);
    }
  }
}

function onAppendDragOver(e) {
  if (!draggedEl) return;
  e.preventDefault();
  e.stopPropagation();
  e.dataTransfer.dropEffect = 'move';
  
  // Show ghost preview inside the chapter by inserting after the drop zone
  const dropZone = e.currentTarget;
  if (dropZone.nextSibling !== draggedEl && dropZone.parentNode) {
    dropZone.parentNode.insertBefore(draggedEl, dropZone.nextSibling);
  }
}

function onAppendDrop(e) {
  if (!draggedEl) return;
  e.preventDefault();
  e.stopPropagation();
  const parentId = e.currentTarget.dataset?.parentId || '';
  console.log('[drag-drop] drop to append as child', { parentId });
  // ensure draggedEl looks solid before performing move
  draggedEl.style.opacity = '1';
  draggedEl.style.pointerEvents = 'auto';
  performMove('', parentId);
}

function onHeaderDragOver(e) {
  if (!draggedEl) return;
  e.preventDefault();
  e.stopPropagation();
  e.dataTransfer.dropEffect = 'move';
  
  // Find the chapter section and its append drop zone
  const chapterSection = e.currentTarget.closest('.chapter-section');
  if (!chapterSection) return;
  
  const appendZone = chapterSection.querySelector('.chapter-append-drop');
  if (!appendZone) return;
  
  // Show ghost preview after the append zone (as first child)
  if (appendZone.nextSibling !== draggedEl && appendZone.parentNode) {
    appendZone.parentNode.insertBefore(draggedEl, appendZone.nextSibling);
  }
}

function onHeaderDrop(e) {
  if (!draggedEl) return;
  e.preventDefault();
  e.stopPropagation();
  
  // Find the chapter section
  const chapterSection = e.currentTarget.closest('.chapter-section');
  if (!chapterSection) return;
  
  const parentId = chapterSection.dataset?.chapterId || '';
  
  // Find the first child to insert before it (to place at top)
  const childrenContainer = chapterSection.querySelector('.chapter-children');
  let targetId = '';
  if (childrenContainer) {
    const firstChild = childrenContainer.querySelector('.chapter-section');
    if (firstChild && firstChild !== draggedEl) {
      targetId = firstChild.dataset?.chapterId || '';
    }
  }
  
  console.log('[drag-drop] drop on chapter header to insert as first child', { parentId, targetId });
  
  // ensure draggedEl looks solid before performing move
  draggedEl.style.opacity = '1';
  draggedEl.style.pointerEvents = 'auto';
  performMove(targetId, parentId);
}

function onDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  if (!draggedEl) return;

  const draggedType = draggedEl.dataset.chapterType || 'chapter';

  // Get the actual parent context from where the ghost block is now positioned
  let targetId = '';
  let parentId = '';
  
  const nextSibling = draggedEl.nextElementSibling;
  if (nextSibling && nextSibling.classList.contains('chapter-section')) {
    // Dropped before a sibling block
    targetId = nextSibling.dataset?.chapterId || '';
    parentId = nextSibling.dataset?.parentId || '';
    console.log('[drag-drop] drop before sibling', { targetId, parentId });
  } else {
    // Dropped at end - infer parent from container
    const container = draggedEl.parentElement;
    if (container) {
      if (container.classList.contains('chapter-children')) {
        // Inside a chapter's children container
        const parentSection = container.closest('.chapter-section');
        parentId = parentSection?.dataset?.chapterId || '';
        targetId = '';
        console.log('[drag-drop] drop at end of chapter', { parentId });
      } else {
        // Root level
        parentId = '';
        targetId = '';
        console.log('[drag-drop] drop at root end');
      }
    }
  }

  // Validate: non-chapter blocks cannot be at root
  if (draggedType !== 'chapter' && parentId === '') {
    console.warn('[drag-drop] Blocked: non-chapter block cannot be at root');
    alert('Only chapter blocks can be placed at root level.');
    window.location.reload();
    return;
  }

  console.log('[drag-drop] drop final params', { 
    dragged: draggedEl.dataset.chapterId, 
    target: targetId, 
    parent: parentId 
  });

  // Make the block solid again before move
  if (draggedEl) {
    draggedEl.style.opacity = '1';
    draggedEl.style.pointerEvents = 'auto';
  }

  performMove(targetId, parentId);
}

function performMove(targetId, parentId = '') {
  const chapterId = draggedEl.dataset.chapterId;
  const noteId = document.querySelector('[data-note-id]')?.dataset.noteId;

  if (!noteId || !chapterId) {
    console.error('performMove: missing noteId or chapterId', { noteId, chapterId });
    return;
  }

  // Prevent non-chapter blocks from being moved to root
  const draggedType = draggedEl.dataset.chapterType || 'chapter';
  if ((parentId === '' || parentId === null) && draggedType !== 'chapter') {
    // Inform the user and restore UI by reloading (server state unchanged)
    alert('Only chapter blocks may be moved to root level.');
    window.location.reload();
    return;
  }

  console.log('performMove: attempting move', { noteId, chapterId, targetId, parentId });
  
  const form = new FormData();
  form.append('target_id', targetId);
  form.append('parent_id', parentId);

  fetch(`/notes/${noteId}/chapters/${chapterId}/move`, {
    method: 'POST',
    body: form,
    headers: { 'HX-Request': 'true' }
  })
  .then(res => {
    console.log('performMove: response status', res.status);
    if (!res.ok) {
      return res.text().then(text => {
        const error = `Move failed with status ${res.status}: ${text}`;
        console.error('performMove: HTTP error', error);
        throw new Error(error);
      });
    }
    return res.text();
  })
  .then(html => {
    console.log('performMove: received HTML response, parsing for OOB elements');
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    
    const oobElements = doc.querySelectorAll('[hx-swap-oob]');
    console.log('performMove: found', oobElements.length, 'OOB elements');
    
    if (oobElements.length === 0) {
      console.warn('performMove: no OOB elements found, reloading page');
      window.location.reload();
      return;
    }
    
    oobElements.forEach(el => {
      const swapType = el.getAttribute('hx-swap-oob');
      const existing = document.getElementById(el.id);
      console.log('performMove: applying OOB swap', { id: el.id, swapType, elementExists: !!existing });
      if (existing) {
        if (swapType === 'outerHTML') {
          existing.outerHTML = el.outerHTML;
        } else if (swapType === 'innerHTML') {
          existing.innerHTML = el.innerHTML;
        } else {
          existing.outerHTML = el.outerHTML;
        }
      }
    });
    
    console.log('performMove: reinitializing drag and drop');
    setTimeout(() => initDragAndDrop(), 100);
  })
  .catch(err => {
    console.error('performMove: FAILED:', err);
    alert(`Move operation failed: ${err.message}\n\nReloading page to restore state.`);
    window.location.reload();
  });
}

export function initDragAndDrop() {
  const handles = document.querySelectorAll('.drag-handle');
  console.log('[drag-drop] init: handles=', handles.length);
  handles.forEach(handle => {
    handle.setAttribute('draggable', 'true');
    handle.addEventListener('dragstart', onDragStart);
    handle.addEventListener('dragend', onDragEnd);
  });

  const sections = document.querySelectorAll('.chapter-section');
  console.log('[drag-drop] init: sections=', sections.length);
  sections.forEach(section => {
    section.addEventListener('dragover', onDragOver);
    section.addEventListener('drop', onDrop);
  });

  // Append-child persistent drop areas
  const appendZones = document.querySelectorAll('.chapter-append-drop');
  console.log('[drag-drop] init: append-drop zones=', appendZones.length);
  appendZones.forEach(zone => {
    zone.addEventListener('dragover', onAppendDragOver);
    zone.addEventListener('drop', onAppendDrop);
  });

  // Chapter headers as drop targets for appending as child
  const chapterHeaders = document.querySelectorAll('.chapter-header');
  console.log('[drag-drop] init: chapter headers=', chapterHeaders.length);
  chapterHeaders.forEach(header => {
    header.addEventListener('dragover', onHeaderDragOver);
    header.addEventListener('drop', onHeaderDrop);
  });

  // Allow drop anywhere to prevent browser defaults
  // Make global drag handlers selective: only prevent default when over known drop areas
  document.addEventListener('dragover', (e) => {
    if (!draggedEl) return;
    const isHandled = !!e.target.closest('.chapter-section, .chapter-append-drop, .chapter-header, .chapters-display');
    if (isHandled) e.preventDefault();
  });

  document.addEventListener('drop', (e) => {
    if (!draggedEl) return;
    console.log('[drag-drop] document-level drop captured');
    e.preventDefault();
    e.stopPropagation();
    
    // If we have a dragged element positioned somewhere, process the drop
    onDrop(e);
  });

  // Root-level container: allow drops only for `chapter` type blocks
  const rootContainer = document.querySelector('.chapters-display');
  if (rootContainer) {
    rootContainer.addEventListener('dragover', (e) => {
      if (!draggedEl) return;
      const draggedType = draggedEl.dataset.chapterType || 'chapter';
      if (draggedType !== 'chapter') {
        // do not call preventDefault -> drop not allowed here
        e.dataTransfer.dropEffect = 'none';
        return;
      }
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });

    rootContainer.addEventListener('drop', (e) => {
      if (!draggedEl) return;
      const draggedType = draggedEl.dataset.chapterType || 'chapter';
      if (draggedType !== 'chapter') {
        console.warn('Root drop blocked for non-chapter type');
        // restore UI
        window.location.reload();
        return;
      }
      // Allowed: perform append to root (end)
      e.preventDefault();
      e.stopPropagation();
      performMove('', '');
    });
  }
}

