/**
 * Shared CodeMirror configuration and initialization
 * Used by the main app editor
 */

export const CODEMIRROR_CONFIG = {
  mode: 'application/json',
  lineNumbers: true,
  indentUnit: 2,
  tabSize: 2,
  indentWithTabs: false,
  theme: 'dracula',
  keyMap: 'default',
  lineWrapping: true,
  gutters: ['CodeMirror-linenumbers', 'CodeMirror-lint-markers'],
  lint: true,
  autoCloseBrackets: true,
};

/**
 * Create extraKeys configuration with callbacks
 * @param {Object} callbacks - { onEnter, onShiftEnter }
 */
export function createExtraKeys(callbacks = {}) {
  return {
    'Enter': (cm) => {
      if (callbacks.onEnter) {
        callbacks.onEnter(cm);
      }
    },
    'Shift-Enter': (cm) => {
      if (callbacks.onShiftEnter) {
        callbacks.onShiftEnter(cm);
      } else {
        // Default: insert newline with auto-indentation
        cm.execCommand('newlineAndIndent');
      }
    },
  };
}

/**
 */
