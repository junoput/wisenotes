/**
 * CodeMirror Editor for Code Blocks
 * Self-contained editor implementation for the code block type
 */

import { Editor } from '/static/js/editors/editor-base.js';

/**
 * CodeMirror configuration for code blocks
 */
const CODEMIRROR_CONFIG = {
  lineNumbers: true,
  indentUnit: 2,
  tabSize: 2,
  indentWithTabs: false,
  theme: 'dracula',
  keyMap: 'default',
  lineWrapping: true,
  autoCloseBrackets: true,
};

/**
 * Language mode to MIME type mapping
 */
const MIME_TYPES = {
  python: 'text/x-python',
  javascript: 'text/javascript',
  typescript: 'text/typescript',
  java: 'text/x-java',
  go: 'text/x-go',
  rust: 'text/x-rustsrc',
  clike: 'text/x-csrc',
};

/**
 * CodeMirror Editor Implementation for Code Blocks
 */
export class CodeBlockEditor extends Editor {
  constructor(container, options = {}) {
    super(container, options);
    this.editor = null;
  }

  async mount() {
    console.log('[CodeBlockEditor] mount() called');
    console.log('[CodeBlockEditor] container:', this.container);
    
    // Dynamically load CodeMirror if not already loaded
    if (!window.CodeMirror) {
      console.log('[CodeBlockEditor] CodeMirror not loaded, loading...');
      await this._loadCodeMirror();
      console.log('[CodeBlockEditor] CodeMirror loaded successfully');
    } else {
      console.log('[CodeBlockEditor] CodeMirror already loaded');
    }

    const textarea = this.container.querySelector('textarea');
    console.log('[CodeBlockEditor] textarea found:', textarea);
    if (!textarea) {
      console.error('[CodeBlockEditor] No textarea found in container');
      throw new Error('No textarea found in container');
    }

    const modeAttr = this.container.dataset.codemirrorMode;
    const language = this.container.dataset.language;
    
    // Load language mode if needed
    if (modeAttr) {
      await this._loadLanguageMode(modeAttr);
    }

    const mode = this._getMimeType(modeAttr, language);
    const config = {
      ...CODEMIRROR_CONFIG,
      mode,
      extraKeys: {
        'Shift-Enter': (cm) => cm.execCommand('newlineAndIndent'),
      },
    };

    console.log('[CodeBlockEditor] Creating CodeMirror with config:', config);
    // Create CodeMirror instance
    this.editor = window.CodeMirror.fromTextArea(textarea, config);
    console.log('[CodeBlockEditor] CodeMirror instance created:', this.editor);

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

    // Set initial focus
    this.focus();
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
      // Place cursor at end
      const lastLine = this.editor.lastLine();
      this.editor.setCursor(lastLine, this.editor.getLine(lastLine).length);
    }
  }

  _getMimeType(mode, language) {
    // Use mode if provided, otherwise derive from language
    const key = mode || language || 'javascript';
    return MIME_TYPES[key] || MIME_TYPES.javascript;
  }

  async _loadCodeMirror() {
    return new Promise((resolve, reject) => {
      // Load base CSS
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/static/vendor/codemirror/codemirror.css';
      document.head.appendChild(link);

      // Load dracula theme CSS
      const themeLink = document.createElement('link');
      themeLink.rel = 'stylesheet';
      themeLink.href = '/static/vendor/codemirror/dracula.css';
      document.head.appendChild(themeLink);

      // Load core JS
      const script = document.createElement('script');
      script.src = '/static/vendor/codemirror/codemirror.js';
      script.onload = () => {
        // Load auto-close brackets addon
        const bracketsScript = document.createElement('script');
        bracketsScript.src = '/static/vendor/codemirror/addon/edit/closebrackets.js';
        bracketsScript.onload = () => resolve();
        bracketsScript.onerror = () => reject(new Error('Failed to load closebrackets addon'));
        document.head.appendChild(bracketsScript);
      };
      script.onerror = () => reject(new Error('Failed to load CodeMirror'));
      document.head.appendChild(script);
    });
  }

  async _loadLanguageMode(mode) {
    return new Promise((resolve, reject) => {
      // Check if mode is already loaded
      if (window.CodeMirror && window.CodeMirror.modes[mode]) {
        resolve();
        return;
      }

      const script = document.createElement('script');
      script.src = `/static/vendor/codemirror/${mode}.js`;
      script.onload = () => resolve();
      script.onerror = () => {
        console.warn(`Failed to load CodeMirror mode: ${mode}`);
        resolve(); // Don't fail, just use default mode
      };
      document.head.appendChild(script);
    });
  }
}

// Register this editor globally for the app's editor loading system
if (!window.editorRegistry) {
  window.editorRegistry = {};
}
window.editorRegistry['code-block'] = CodeBlockEditor;
