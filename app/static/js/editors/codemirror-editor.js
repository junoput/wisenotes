import { Editor } from './editor-base.js';
import { CODEMIRROR_CONFIG, createExtraKeys } from '../codemirror-config.js';

/**
 * CodeMirror Editor Implementation
 * Advanced editor with syntax highlighting, linting, and custom keybindings
 */
export class CodeMirrorEditor extends Editor {
  constructor(container, options = {}) {
    super(container, options);
    this.editor = null;
  }

  async mount() {
    // Dynamically load CodeMirror if not already loaded
    if (!window.CodeMirror) {
      await this._loadCodeMirror();
    }

    const textarea = this.container.querySelector('textarea');
    if (!textarea) {
      throw new Error('No textarea found in container');
    }

    const modeAttr = this.container.dataset.codemirrorMode || CODEMIRROR_CONFIG.mode;
    const language = this.container.dataset.language;
    
    // Load language mode if needed
    if (modeAttr && modeAttr !== 'application/json') {
      await this._loadLanguageMode(modeAttr);
    }

    const mode = this._getMimeType(modeAttr, language);
    const isJsonMode = mode === 'application/json';
    const config = {
      ...CODEMIRROR_CONFIG,
      mode,
      lint: isJsonMode ? CODEMIRROR_CONFIG.lint : false,
      extraKeys: createExtraKeys(
        isJsonMode
          ? {
              onEnter: (cm) => this._handleEnter(cm),
              onShiftEnter: (cm) => cm.execCommand('newlineAndIndent'),
            }
          : {}
      ),
    };

    // Create CodeMirror instance anchored to the textarea position
    this.editor = window.CodeMirror.fromTextArea(textarea, config);

    // Ensure the CodeMirror wrapper stays above the button row
    const wrapper = this.editor.getWrapperElement();
    const buttonRow = this.container.querySelector('.chapter-edit-form > div:last-of-type');
    if (wrapper && buttonRow && buttonRow.parentNode === this.container.querySelector('.chapter-edit-form')) {
      buttonRow.parentNode.insertBefore(wrapper, buttonRow);
    }

    // Update textarea on change for form submission
    this.editor.on('change', () => {
      textarea.value = this.editor.getValue();
    });

    this._placeInitialCursor();
  }

  unmount() {
    if (this.editor) {
      const wrapper = this.editor.getWrapperElement();
      if (wrapper && wrapper.parentNode) {
        wrapper.parentNode.removeChild(wrapper);
      }
      this.editor = null;
    }
  }

  getValue() {
    return this.editor ? this.editor.getValue() : '';
  }

  setValue(content) {
    if (this.editor) {
      this.editor.setValue(content);
    }
  }

  focus() {
    if (this.editor) {
      this.editor.focus();
      // Keep cursor visible at a sensible position
      const pos = this._findFirstEditablePosition();
      this.editor.setCursor(pos);
    }
  }

  _handleEnter(cm) {
    // If this Enter came with Shift, treat it as a plain newline (do not submit)
    const evt = cm?.state?.keyEvent;
    if (evt && evt.shiftKey) {
      try {
        evt.preventDefault();
        evt.stopPropagation();
      } catch (err) {
        // ignore
      }
      cm.execCommand('newlineAndIndent');
      return;
    }

    // Sync textarea with editor content
    const textarea = this.container.querySelector('textarea');
    if (textarea) {
      textarea.value = this.editor.getValue();
    }

    // Only auto-submit for JSON mode where Enter acts as submit
    const mode = this.editor?.getOption('mode');
    if (mode !== 'application/json') {
      cm.execCommand('newlineAndIndent');
      return;
    }

    // Block submit if JSON is invalid
    try {
      JSON.parse(this.editor.getValue());
    } catch (err) {
      console.warn('Submit blocked: JSON parse error', err?.message || err);
      return;
    }
    
    // Submit the form
    const form = this.container.querySelector('form');
    if (form) {
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.click();
      }
    }
  }

  _placeInitialCursor() {
    this.editor.focus();
    const pos = this._findFirstEditablePosition();
    this.editor.setCursor(pos);
  }

  _findFirstEditablePosition() {
    // Try to position right after the '[' of the "content" array; otherwise start of document
    try {
      const value = this.editor.getValue();
      const lines = value.split('\n');
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].includes('"content"')) {
          // Prefer placing cursor immediately after '[' on same line if present
          const sameLineBracketIdx = lines[i].indexOf('[');
          if (sameLineBracketIdx !== -1) {
            return { line: i, ch: sameLineBracketIdx + 1 };
          }
          // Otherwise, search subsequent lines for the first '[' and place after it
          for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) {
            const nextBracketIdx = lines[j].indexOf('[');
            if (nextBracketIdx !== -1) {
              return { line: j, ch: nextBracketIdx + 1 };
            }
            // If we encounter a ']' before '[', break out as the array seems empty/closed
            if (lines[j].includes(']')) break;
          }
          // Fallback: put cursor at start of next line with one indent level
          const nextLine = Math.min(i + 1, lines.length - 1);
          const baseIndent = (lines[i].match(/^\s*/)?.[0] || '');
          const indentUnit = this.editor.getOption('indentUnit') || 2;
          const indent = baseIndent + ' '.repeat(indentUnit);
          return { line: nextLine, ch: indent.length };
        }
      }
    } catch {}
    return { line: 0, ch: 0 };
  }

  async _loadCodeMirror() {
    return new Promise((resolve, reject) => {
      // Load base CSS from local vendor
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/static/vendor/codemirror/codemirror.css';
      document.head.appendChild(link);

      // Load dracula theme CSS
      const themeLink = document.createElement('link');
      themeLink.rel = 'stylesheet';
      themeLink.href = '/static/vendor/codemirror/dracula.css';
      document.head.appendChild(themeLink);

      // Load lint CSS
      const lintLink = document.createElement('link');
      lintLink.rel = 'stylesheet';
      lintLink.href = '/static/vendor/codemirror/addon/lint/lint.css';
      document.head.appendChild(lintLink);

      // Load core JS from local vendor
      const script = document.createElement('script');
      script.src = '/static/vendor/codemirror/codemirror.js';
      script.onload = () => {
        // Load auto-close addon next so bracket pairing works everywhere
        const closeBracketsScript = document.createElement('script');
        closeBracketsScript.src = '/static/vendor/codemirror/addon/edit/closebrackets.js';
        closeBracketsScript.onload = () => {
          // Load JSON mode
          const jsonScript = document.createElement('script');
          jsonScript.src = '/static/vendor/codemirror/javascript.js';
          jsonScript.onload = () => {
            // Load jsonlint first, then lint core, then JSON lint adapter
            const jsonlintLib = document.createElement('script');
            jsonlintLib.src = '/static/vendor/codemirror/addon/lint/jsonlint.js';
            jsonlintLib.onload = () => {
              const lintScript = document.createElement('script');
              lintScript.src = '/static/vendor/codemirror/addon/lint/lint.js';
              lintScript.onload = () => {
                const jsonLintScript = document.createElement('script');
                jsonLintScript.src = '/static/vendor/codemirror/addon/lint/json-lint.js';
                jsonLintScript.onload = resolve;
                jsonLintScript.onerror = reject;
                document.head.appendChild(jsonLintScript);
              };
              lintScript.onerror = reject;
              document.head.appendChild(lintScript);
            };
            jsonlintLib.onerror = reject;
            document.head.appendChild(jsonlintLib);
          };
          jsonScript.onerror = reject;
          document.head.appendChild(jsonScript);
        };
        closeBracketsScript.onerror = reject;
        document.head.appendChild(closeBracketsScript);
      };
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  async _loadLanguageMode(mode) {
    const modeFiles = {
      'python': '/static/vendor/codemirror/python.js',
      'javascript': '/static/vendor/codemirror/javascript.js',
      'go': '/static/vendor/codemirror/go.js',
      'rust': '/static/vendor/codemirror/rust.js',
      'clike': '/static/vendor/codemirror/clike.js',
    };

    const modeFile = modeFiles[mode];
    if (!modeFile) return;

    // Check if already loaded
    const scriptId = `cm-mode-${mode}`;
    if (document.getElementById(scriptId)) return;

    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.id = scriptId;
      script.src = modeFile;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  _getMimeType(mode, language) {
    const mimeMap = {
      'python': 'text/x-python',
      'javascript': language === 'typescript' ? 'text/typescript' : 'text/javascript',
      'go': 'text/x-go',
      'rust': 'text/x-rustsrc',
      'clike': 'text/x-java',
      'application/json': 'application/json',
    };
    return mimeMap[mode] || mode;
  }
}

