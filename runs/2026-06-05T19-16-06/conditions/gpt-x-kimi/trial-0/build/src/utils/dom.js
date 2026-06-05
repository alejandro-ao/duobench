// ============================================
// Vanilla WebOS — DOM Utilities
// ============================================

const DOM = {
  /**
   * Create an element with optional class, attributes, and children.
   */
  create(tag, opts = {}) {
    const el = document.createElement(tag);
    if (opts.className) el.className = opts.className;
    if (opts.id) el.id = opts.id;
    if (opts.attrs) {
      Object.entries(opts.attrs).forEach(([k, v]) => el.setAttribute(k, v));
    }
    if (opts.styles) Object.assign(el.style, opts.styles);
    if (opts.text) el.textContent = opts.text;
    if (opts.html) el.innerHTML = opts.html;
    if (opts.children) opts.children.forEach(c => el.appendChild(c));
    if (opts.parent) opts.parent.appendChild(el);
    return el;
  },

  /**
   * Empty an element.
   */
  empty(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  },

  /**
   * Debounce a function.
   */
  debounce(fn, ms = 200) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  },

  /**
   * Format a date nicely.
   */
  formatDate(ts) {
    const d = new Date(ts);
    return d.toLocaleString();
  },

  /**
   * Format relative time.
   */
  timeAgo(ts) {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return "just now";
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  }
};
