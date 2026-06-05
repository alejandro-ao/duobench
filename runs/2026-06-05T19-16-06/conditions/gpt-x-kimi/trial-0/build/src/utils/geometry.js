// ============================================
// Vanilla WebOS — Geometry Utilities
// ============================================

const Geometry = {
  clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  },

  dist(x1, y1, x2, y2) {
    return Math.hypot(x2 - x1, y2 - y1);
  },

  rectCenter(rect) {
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    };
  },

  snapToGrid(value, gridSize) {
    return Math.round(value / gridSize) * gridSize;
  }
};
