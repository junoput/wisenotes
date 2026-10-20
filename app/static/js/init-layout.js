/**
 * Initialize CSS variables from localStorage before page renders
 * This prevents layout jitter when restoring pane state
 */
(function() {
  // Scripts run: style.css keys the narrow notes dropdown on this class, so a
  // page without scripts keeps the notes list in the page flow instead of a
  // fixed overlay nothing but the summary can close (20261019-019).
  document.documentElement.classList.add('js');
  const notesCollapsed = localStorage.getItem('pane:note-list:collapsed') === '1';
  document.documentElement.style.setProperty('--notes-col', notesCollapsed ? '48px' : '260px');
})();
