// ============================================
// Vanilla WebOS — EventBus
// ============================================

class EventBus {
  constructor() {
    /** @type {Map<string, Set<Function>>} */
    this.listeners = new Map();
  }

  /**
   * Subscribe to an event.
   * @param {string} event
   * @param {Function} fn
   * @returns {Function} unsubscribe
   */
  on(event, fn) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(fn);
    return () => this.off(event, fn);
  }

  /**
   * Unsubscribe from an event.
   * @param {string} event
   * @param {Function} fn
   */
  off(event, fn) {
    this.listeners.get(event)?.delete(fn);
  }

  /**
   * Emit an event to all listeners.
   * @param {string} event
   * @param {*} payload
   */
  emit(event, payload) {
    this.listeners.get(event)?.forEach(fn => {
      try { fn(payload); } catch (e) { console.error(e); }
    });
  }
}
