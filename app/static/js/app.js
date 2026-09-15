/* Wisenotes enhancements. Everything here is optional: the pages work with
 * scripts off. htmx handles the requests; this file adds keyboard focus,
 * pane state, confirm dialogs, CodeMirror in code-block editors, KaTeX for
 * math blocks, and re-runs those after htmx swaps. */
import { initDragAndDrop } from '/static/js/drag-drop.js';

const NARROW = '(max-width: 960px)';
const isNarrow = () => window.matchMedia(NARROW).matches;
const root = document.documentElement;

// ---------------------------------------------------------------- panes

function setCollapsed(pane, collapsed) {
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

function restorePanes() {
  const pane = document.getElementById('note-list');
  if (!pane) return;
  const collapsed = isNarrow() || localStorage.getItem('pane:note-list:collapsed') === '1';
  setCollapsed(pane, collapsed);
}

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

function focusFirstNote() {
  (document.querySelector('[data-focus-first]') || document.querySelector('.note-list .item'))?.focus({ preventScroll: true });
}

// Bare Shift: first note, then cycle through blocks.
window.addEventListener('keydown', (e) => {
  if (e.key !== 'Shift' || e.ctrlKey || e.altKey || e.metaKey || e.repeat || typing(document.activeElement)) return;
  e.preventDefault();
  const sections = [...document.querySelectorAll('.chapter-section')];
  const idx = sections.indexOf(document.activeElement);
  if (idx === -1 && document.querySelector('.note-list .item')) return focusFirstNote();
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

function closeSettings() { document.getElementById('note-settings')?.remove(); }
document.body.addEventListener('close-note-settings', closeSettings);
document.body.addEventListener('click', (e) => {
  if (e.target.closest('[data-close-settings]')) { e.preventDefault(); closeSettings(); }
});

// ---------------------------------------------------------------- code and math

const CM = '/static/vendor/codemirror';
const CM_MODE = { python: 'python', javascript: 'javascript', typescript: 'javascript', go: 'go', rust: 'rust', java: 'clike' };
const CM_MIME = { python: 'text/x-python', javascript: 'text/javascript', typescript: 'text/typescript', go: 'text/x-go', rust: 'text/x-rustsrc', java: 'text/x-java' };

function loadOnce(tag, attrs) {
  const key = attrs.src || attrs.href;
  if (document.querySelector(`${tag}[${attrs.src ? 'src' : 'href'}="${key}"]`)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const el = Object.assign(document.createElement(tag), attrs, { onload: resolve, onerror: reject });
    document.head.appendChild(el);
  });
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
        mode: CM_MIME[lang] || 'text/javascript', theme: 'dracula', lineNumbers: true,
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

function renderMath() {
  if (typeof katex === 'undefined') return;
  for (const el of document.querySelectorAll('.math-block-display .math-formula-content')) {
    if (el._rendered) continue;
    const formula = el.textContent.trim();
    if (!formula) continue;
    const displayMode = el.parentElement.dataset.language !== 'asciimath';
    try { katex.render(formula, el, { displayMode, throwOnError: false }); el._rendered = true; }
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
  initDragAndDrop();
}

document.addEventListener('DOMContentLoaded', () => { enhance(); focusFirstNote(); });
window.addEventListener('load', renderMath); // KaTeX is deferred; it may land after DOMContentLoaded
document.body.addEventListener('htmx:beforeSwap', () => {
  document.querySelectorAll('.chapter-edit-mode').forEach((box) => { box._cm?.toTextArea(); box._cm = null; });
});
document.body.addEventListener('htmx:afterSwap', (e) => {
  enhance();
  if (e.detail?.target?.closest?.('#note-list') || e.detail?.target?.id === 'note-list') setTimeout(focusFirstNote, 0);
});
