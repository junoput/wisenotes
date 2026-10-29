/* Wisenotes enhancements. Everything here is optional: the pages work with
 * scripts off. htmx handles the requests; this file adds keyboard focus,
 * pane state, confirm dialogs, CodeMirror in code-block editors, KaTeX for
 * math blocks, and re-runs those after htmx swaps. */
import { initDragAndDrop } from '/static/js/drag-drop.js';
import { renderGraphs, redrawOnThemeChange } from '/static/js/graph.js';

const NARROW = '(max-width: 960px)';
const isNarrow = () => window.matchMedia(NARROW).matches;
const root = document.documentElement;
const isLight = () => getComputedStyle(root).colorScheme === 'light';

// ---------------------------------------------------------------- panes

function setCollapsed(pane, collapsed) {
  if (pane.tagName === 'DETAILS' && pane.open === collapsed) pane.open = !collapsed; // the <details> is the truth; the class mirrors it for CSS
  pane.classList.toggle('collapsed', collapsed);
  const content = pane.querySelector('.pane-content');
  if (content) content.style.display = collapsed ? 'none' : '';
  const colVar = pane.getAttribute('data-col-var');
  if (colVar && !isNarrow()) root.style.setProperty(colVar, collapsed ? '48px' : '260px');
  if (isNarrow() && pane.id === 'note-list') {
    document.querySelector('.narrow-notes-toggle')?.classList.toggle('pane-open', !collapsed);
    document.body.classList.toggle('notes-dropdown-open', !collapsed);
    setTimeout(positionDropdown, 10);
  }
}

const noteOpen = () => Boolean(document.getElementById('editor')?.dataset.noteId);

function restorePanes() {
  const pane = document.getElementById('note-list');
  if (!pane) return;
  // Narrow: the list is a dropdown under an open note, but with no note open it
  // IS the page, and nothing else on it could open it again (20261014-187).
  const collapsed = isNarrow() ? noteOpen() : localStorage.getItem('pane:note-list:collapsed') === '1';
  setCollapsed(pane, collapsed);
}

// The summary toggles the <details> natively; mirror that into the class and remember it.
document.body.addEventListener('toggle', (e) => {
  const pane = e.target;
  if (!(pane instanceof HTMLDetailsElement) || pane.id !== 'note-list') return;
  setCollapsed(pane, !pane.open);
  if (!isNarrow()) localStorage.setItem('pane:note-list:collapsed', pane.open ? '0' : '1');
}, true);

document.body.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-toggle-pane]');
  if (!btn) return;
  const pane = document.getElementById(btn.getAttribute('data-toggle-pane'));
  if (!pane) return;
  const collapsed = !pane.classList.contains('collapsed');
  setCollapsed(pane, collapsed);
  if (!isNarrow()) localStorage.setItem(`pane:${pane.id}:collapsed`, collapsed ? '1' : '0');
});

// Narrow mode: picking a note closes the dropdown.
document.body.addEventListener('click', (e) => {
  if (!isNarrow() || !e.target.closest('#note-list .item')) return;
  const pane = document.getElementById('note-list');
  setTimeout(() => pane && !pane.classList.contains('collapsed') && setCollapsed(pane, true), 150);
});

function positionDropdown() {
  const noteList = document.getElementById('note-list');
  const header = document.querySelector('.pane.editor .pane-header');
  if (!noteList || !header) return;
  noteList.style.top = isNarrow() ? `${header.getBoundingClientRect().bottom}px` : '';
}

function initStickyHeader() {
  const pane = document.querySelector('.pane.editor');
  const header = pane?.querySelector('.pane-header');
  if (!pane || !header || pane.querySelector('.sticky-sentinel')) return;
  const sentinel = document.createElement('div');
  sentinel.className = 'sticky-sentinel';
  sentinel.style.cssText = 'position:absolute;top:0;height:1px;width:1px;pointer-events:none';
  pane.style.position = 'relative';
  pane.insertBefore(sentinel, header);
  new IntersectionObserver(([entry]) => {
    header.classList.toggle('stuck', !entry.isIntersecting);
    positionDropdown();
  }).observe(sentinel);
}

window.addEventListener('scroll', () => requestAnimationFrame(positionDropdown), { passive: true });
window.addEventListener('resize', positionDropdown);

// ---------------------------------------------------------------- keyboard

const typing = (el) => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);

// The open note's item if there is one, else the first. Focusing the first item
// while another note was open drew a focus ring on a note nobody had chosen
// (20261019-010). An item in a collapsed folder is display:none and takes no
// focus, so the next candidate is tried until one does.
function focusNote() {
  const candidates = [document.querySelector('.note-list .item.active'),
    document.querySelector('[data-focus-first]'), ...document.querySelectorAll('.note-list .item')];
  for (const el of candidates) {
    el?.focus({ preventScroll: true });
    if (el && document.activeElement === el) return;
  }
}

// Bare Shift: first note, then cycle through blocks.
window.addEventListener('keydown', (e) => {
  if (e.key !== 'Shift' || e.ctrlKey || e.altKey || e.metaKey || e.repeat || typing(document.activeElement)) return;
  e.preventDefault();
  const sections = [...document.querySelectorAll('.chapter-section')];
  const idx = sections.indexOf(document.activeElement);
  if (idx === -1 && document.querySelector('.note-list .item')) return focusNote();
  sections[(idx + 1) % sections.length]?.focus();
}, true);

// Enter saves a block editor; Shift+Enter is a newline.
document.body.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  const form = e.target.closest('form.chapter-edit-form');
  if (form) { e.preventDefault(); form.requestSubmit(); }
});

// ---------------------------------------------------------------- forms and overlays

document.body.addEventListener('submit', (e) => {
  const form = e.target.closest('form[data-confirm]');
  if (form && !window.confirm(form.getAttribute('data-confirm'))) { e.preventDefault(); e.stopPropagation(); }
}, true);

// Overlays (note settings, add a note) are appended to <body> by htmx; closing removes them.
function closeSettings() { document.querySelectorAll('.note-settings-overlay').forEach((el) => el.remove()); }
document.body.addEventListener('close-note-settings', closeSettings);
document.body.addEventListener('click', (e) => {
  if (e.target.closest('[data-close-settings]') || e.target.classList.contains('note-settings-overlay')) {
    e.preventDefault(); closeSettings();
  }
});
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && document.querySelector('.note-settings-overlay')) closeSettings();
});
// A second click on "+" would stack a second overlay; drop the old one first.
document.body.addEventListener('htmx:beforeSwap', (e) => {
  if (e.detail.requestConfig?.path === '/notes/new') closeSettings();
});
// A refused import answers 400 with the reason, a refused media delete or pick 409
// with the gallery as it is now, and a refused note delete 409 with the reason; htmx
// drops 4xx bodies unless told, which left the overlay open, or the stale gallery
// in place, with nothing said.
const MEDIA_DELETE = /^\/notes\/[^/]+\/media\/[^/]+\/delete$/;
const NOTE_DELETE = /^\/notes\/[^/]+\/delete$/;
const MEDIA_SELECT = /^\/notes\/[^/]+\/chapters\/[^/]+\/media\/select$/;
// A refused graph definition answers 400 with the edit form and its reasons by line.
const BLOCK_SAVE = /^\/notes\/[^/]+\/chapters\/[^/]+\/edit$/;
document.body.addEventListener('htmx:beforeSwap', (e) => {
  const path = e.detail.requestConfig?.path || '';
  const status = e.detail.xhr.status;
  if ((path === '/notes/import' && status === 400)
      || (BLOCK_SAVE.test(path) && status === 400)
      || ((MEDIA_DELETE.test(path) || NOTE_DELETE.test(path) || MEDIA_SELECT.test(path)) && status === 409)
      || (NOTE_DELETE.test(path) && status === 500)) {
    e.detail.shouldSwap = true; e.detail.isError = false;
  }
});

// A write refused while a deploy hands over answers 503 with one plain-text sentence
// (the write fence in app/main.py). htmx shows nothing for a 5xx, so a save looked
// as if it did nothing (20261022-036 review). Without scripts the browser shows the
// 503 page itself; drag-and-drop already alerts with the server's text.
document.body.addEventListener('htmx:responseError', (e) => {
  if (e.detail.xhr.status !== 503) return;
  let note = document.getElementById('save-refused');
  if (!note) {
    note = document.createElement('div');
    note.id = 'save-refused';
    note.className = 'save-refused';
    note.setAttribute('role', 'alert');
    document.body.prepend(note);
  }
  note.textContent = (e.detail.xhr.responseText || 'Not saved. Try again in a moment.').trim().slice(0, 300);
  clearTimeout(note._hide);
  note._hide = setTimeout(() => note.remove(), 10000);
});

// ---------------------------------------------------------------- code and math

const CM = '/static/vendor/codemirror';
const CM_MODE = { python: 'python', javascript: 'javascript', typescript: 'javascript', go: 'go', rust: 'rust', java: 'clike' };
const CM_MIME = { python: 'text/x-python', javascript: 'text/javascript', typescript: 'text/typescript', go: 'text/x-go', rust: 'text/x-rustsrc', java: 'text/x-java' };

// One promise per file: a second caller waits for the load event of the first, it does
// not get a resolved promise because the tag exists. A failed load is forgotten (the
// tag is removed) so that a later call tries again.
const loading = new Map();
function loadOnce(tag, attrs) {
  const key = attrs.src || attrs.href;
  if (loading.has(key)) return loading.get(key);
  const promise = new Promise((resolve, reject) => {
    const el = Object.assign(document.createElement(tag), attrs, {
      onload: () => resolve(),
      onerror: () => {
        loading.delete(key);
        el.remove();
        reject(new Error(`could not load ${key}`));
      },
    });
    document.head.appendChild(el);
  });
  loading.set(key, promise);
  return promise;
}

async function loadCodeMirror(lang) {
  await loadOnce('link', { rel: 'stylesheet', href: `${CM}/codemirror.css` });
  await loadOnce('link', { rel: 'stylesheet', href: `${CM}/dracula.css` });
  await loadOnce('script', { src: `${CM}/codemirror.js` });
  await loadOnce('script', { src: `${CM}/addon/edit/closebrackets.js` });
  await loadOnce('script', { src: `${CM}/${CM_MODE[lang] || 'javascript'}.js` });
}

async function mountCodeEditors() {
  for (const box of document.querySelectorAll('.chapter-edit-mode[data-chapter-type="code"]')) {
    const textarea = box.querySelector('textarea[name="content_text"]');
    if (!textarea || box._cm) continue;
    const select = box.querySelector('select[name="language"]');
    const lang = select?.value || box.dataset.language || 'python';
    try {
      await loadCodeMirror(lang);
      const cm = window.CodeMirror.fromTextArea(textarea, {
        mode: CM_MIME[lang] || 'text/javascript', theme: isLight() ? 'default' : 'dracula', lineNumbers: true,
        indentUnit: 2, tabSize: 2, lineWrapping: true, autoCloseBrackets: true,
        extraKeys: { 'Shift-Enter': (c) => c.execCommand('newlineAndIndent') },
      });
      cm.on('change', () => { textarea.value = cm.getValue(); });
      box._cm = cm;
      select?.addEventListener('change', async () => {
        await loadCodeMirror(select.value);
        cm.setOption('mode', CM_MIME[select.value] || 'text/javascript');
      });
      cm.focus();
    } catch (err) {
      console.warn('CodeMirror unavailable, plain textarea stays', err);
    }
  }
}

// Graph blocks: JSXGraph is loaded the first time one is on the page, like CodeMirror.
function drawGraphs() {
  renderGraphs(loadOnce).catch((err) => console.warn('graphs not drawn, their definitions stay as text', err));
}
redrawOnThemeChange(loadOnce);

function renderMath() {
  if (typeof katex === 'undefined') return;
  for (const el of document.querySelectorAll('.math-block-display .math-formula-content')) {
    if (el._rendered) continue;
    const formula = el.textContent.trim();
    if (!formula) continue;
    const displayMode = el.parentElement.dataset.language !== 'asciimath';
    try {
      katex.render(formula, el, { displayMode, throwOnError: false });
      el._rendered = true;
      el.parentElement.classList.add('math-rendered');
    }
    catch (err) { el.textContent = formula; }
  }
}

// ---------------------------------------------------------------- lifecycle

function enhance() {
  restorePanes();
  initStickyHeader();
  positionDropdown();
  mountCodeEditors();
  renderMath();
  drawGraphs();
  initDragAndDrop();
}

// On load, focus starts in the list only on the home page, where the list is the page;
// with a note open it stays where the page put it, as without scripts.
document.addEventListener('DOMContentLoaded', () => { enhance(); if (!noteOpen()) focusNote(); });
window.addEventListener('load', renderMath); // KaTeX is deferred; it may land after DOMContentLoaded
document.body.addEventListener('htmx:beforeSwap', () => {
  document.querySelectorAll('.chapter-edit-mode').forEach((box) => { box._cm?.toTextArea(); box._cm = null; });
});
document.body.addEventListener('htmx:afterSwap', (e) => {
  enhance();
  if (e.detail?.target?.closest?.('#note-list') || e.detail?.target?.id === 'note-list') setTimeout(focusNote, 0);
});
