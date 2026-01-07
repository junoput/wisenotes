/**
 * Add Button Module
 * Handles hover expansion of available add icons for a single add button.
 */
console.log('[add-button-module] loaded');

export function initAddButtonModule() {
  // Clean up previous handlers if re-initialized
  document.querySelectorAll('.add-block-icon').forEach(btn => {
    if (btn._hoverEnter) {
      btn.removeEventListener('mouseenter', btn._hoverEnter);
      btn.removeEventListener('mouseleave', btn._hoverLeave);
    }
    const section = btn.closest('.chapter-section');
    const menu = section ? section.querySelector('.add-block-menu') : null;

    // Only attach if a menu exists
    if (!menu) return;

    let openTimer = null;
    let closeTimer = null;

    const openMenu = () => {
      // close any other open menus
      document.querySelectorAll('.add-block-menu.visible').forEach(m => {
        if (m !== menu) {
          m.classList.remove('visible', 'horizontal');
          const s = m.closest('.chapter-section');
          if (s) s.classList.remove('add-open');
        }
      });
      menu.classList.add('visible', 'horizontal');
      section.classList.add('add-open');
    };

    const closeMenu = () => {
      menu.classList.remove('visible', 'horizontal');
      section.classList.remove('add-open');
    };

    const onEnter = (e) => {
      clearTimeout(closeTimer);
      openTimer = setTimeout(openMenu, 80);
    };
    const onLeave = (e) => {
      clearTimeout(openTimer);
      closeTimer = setTimeout(closeMenu, 180);
    };

    const onMenuEnter = () => {
      clearTimeout(closeTimer);
      openMenu();
    };
    const onMenuLeave = () => {
      closeTimer = setTimeout(closeMenu, 150);
    };

    btn.addEventListener('mouseenter', onEnter);
    btn.addEventListener('mouseleave', onLeave);
    menu.addEventListener('mouseenter', onMenuEnter);
    menu.addEventListener('mouseleave', onMenuLeave);

    // store references for possible cleanup
    btn._hoverEnter = onEnter;
    btn._hoverLeave = onLeave;
  });
}

// expose as global for synchronous init from app.js
window.initAddButtonModule = initAddButtonModule;
