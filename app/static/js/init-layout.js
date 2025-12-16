/**
 * Initialize CSS variables from localStorage before page renders
 * This prevents layout jitter when restoring pane state
 */
(function() {
  const notesCollapsed = localStorage.getItem('pane:note-list:collapsed') === '1';
  document.documentElement.style.setProperty('--notes-col', notesCollapsed ? '48px' : '260px');
})();
