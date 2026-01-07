/**
 * Add block menu functionality
 * Shows/hides menu on plus icon click
 */

console.log('[add-block.js] module loaded');

let activeMenu = null;

function closeAllMenus() {
  if (activeMenu) {
    activeMenu.classList.remove('visible');
    activeMenu = null;
  }
  // collapse any per-section open state
  document.querySelectorAll('.chapter-section.add-open').forEach(s => s.classList.remove('add-open'));
}

function onAddBlockIconClick(e) {
  e.stopPropagation();
  const icon = e.target.closest('.add-block-icon');
  if (!icon) return;
  const section = icon.closest('.chapter-section');
  const menu = section.querySelector('.add-block-menu');
  if (!menu) return;

  // If this menu is already open, close it
  if (activeMenu === menu) {
    closeAllMenus();
    return;
  }

  // Close other menus first
  closeAllMenus();

  // Open this menu only
  // record how this menu was invoked (child vs after)
  const mode = icon.dataset.addMode || 'after';
  menu.dataset.mode = mode;
  menu.classList.add('visible', 'horizontal');
  section.classList.add('add-open');
  activeMenu = menu;
}

function onAddBlockMenuItemClick(e) {
  const button = e.target.closest('.add-block-menu button');
  if (!button) return;
  
  e.preventDefault();
  e.stopPropagation();
  
  const menu = button.closest('.add-block-menu');
  const icon = menu.previousElementSibling;
  const section = icon.closest('.chapter-section');
  
  const blockType = button.dataset.blockType;
  const noteId = section.dataset.noteId;
  const mode = menu.dataset.mode || 'after';

  let url;
  const form = new FormData();

  if (mode === 'child') {
    // create as child of this section
    const parentId = menu.dataset.parentId || section.dataset.chapterId;
    form.append('parent_id', parentId);
    form.append('block_type', blockType);
    url = `/notes/${noteId}/chapters/child`;
    console.log('[add-block] adding CHILD', { blockType, parentId, noteId });
  } else {
    // default: insert after this section (sibling)
    const prevId = section.dataset.chapterId;
    form.append('prev_id', prevId);
    form.append('block_type', blockType);
    url = `/notes/${noteId}/chapters/after`;
    console.log('[add-block] adding AFTER', { blockType, prevId, noteId });
  }

  fetch(url, {
    method: 'POST',
    body: form,
    headers: { 'HX-Request': 'true' }
  })
  .then(res => {
    if (!res.ok) {
      throw new Error(`Add block failed: ${res.status}`);
    }
    return res.text();
  })
  .then(html => {
    // Parse OOB swaps
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const oobElements = doc.querySelectorAll('[hx-swap-oob]');
    
    oobElements.forEach(el => {
      const existing = document.getElementById(el.id);
      if (existing) {
        const swapType = el.getAttribute('hx-swap-oob');
        if (swapType === 'outerHTML') {
          existing.outerHTML = el.outerHTML;
        } else if (swapType === 'innerHTML') {
          existing.innerHTML = el.innerHTML;
        } else {
          existing.outerHTML = el.outerHTML;
        }
      }
    });
    
    closeAllMenus();
    
    // Re-init drag and drop and add block handlers
    setTimeout(() => {
      if (window.initDragAndDrop) {
        window.initDragAndDrop();
      }
      initAddBlockHandlers();
    }, 100);
  })
  .catch(err => {
    console.error('[add-block] FAILED:', err);
    alert(`Failed to add block: ${err.message}`);
  });
}

export function initAddBlockHandlers() {
  console.log('[add-block] init: setting up handlers');
  
  // Close menu on document click
  document.removeEventListener('click', closeAllMenus);
  document.addEventListener('click', closeAllMenus);
  
  // Attach click handlers to plus icons
  const icons = document.querySelectorAll('.add-block-icon');
  console.log('[add-block] found', icons.length, 'plus icons');
  
  icons.forEach(icon => {
    icon.removeEventListener('click', onAddBlockIconClick);
    icon.addEventListener('click', onAddBlockIconClick);
  });
  
  // Attach click handlers to menu items
  const menuItems = document.querySelectorAll('.add-block-menu button');
  console.log('[add-block] found', menuItems.length, 'menu items');
  
  menuItems.forEach(item => {
    item.removeEventListener('click', onAddBlockMenuItemClick);
    item.addEventListener('click', onAddBlockMenuItemClick);
  });

  // Initialize hover handlers that ensure only one add icon is visible at a time
}
}
