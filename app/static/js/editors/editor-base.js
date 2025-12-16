/**
 * Base Editor Interface
 * All editor implementations should extend this class
 */
export class Editor {
  constructor(container, options = {}) {
    this.container = container;
    this.options = options;
    this._callbacks = {};
  }

  /**
   * Initialize/mount the editor in the container
   */
  mount() {
    throw new Error('mount() must be implemented');
  }

  /**
   * Unmount/destroy the editor
   */
  unmount() {
    throw new Error('unmount() must be implemented');
  }

  /**
   * Get the editor content
   */
  getValue() {
    throw new Error('getValue() must be implemented');
  }

  /**
   * Set the editor content
   */
  setValue(content) {
    throw new Error('setValue() must be implemented');
  }

  /**
   * Focus the editor
   */
  focus() {
    throw new Error('focus() must be implemented');
  }

  /**
   * Register event callbacks
   * Supported events: 'submit', 'change'
   */
  on(event, callback) {
    if (!this._callbacks[event]) {
      this._callbacks[event] = [];
    }
    this._callbacks[event].push(callback);
  }

  /**
   * Emit an event to all registered callbacks
   */
  _emit(event, data) {
    if (this._callbacks[event]) {
      this._callbacks[event].forEach(cb => cb(data));
    }
  }
}
