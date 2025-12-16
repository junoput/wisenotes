import { Editor } from './editor-base.js';

/**
 * Textarea Editor Implementation
 * Simple fallback using native HTML textarea
 */
export class TextareaEditor extends Editor {
  mount() {
    const textarea = this.container.querySelector('textarea');
    if (!textarea) {
      throw new Error('No textarea found in container');
    }
    this.textarea = textarea;
    textarea.focus();
    textarea.setSelectionRange(0, 0);
  }

  unmount() {
    // Nothing to clean up
  }

  getValue() {
    return this.textarea.value;
  }

  setValue(content) {
    this.textarea.value = content;
  }

  focus() {
    this.textarea.focus();
    this.textarea.setSelectionRange(0, 0);
  }
}
