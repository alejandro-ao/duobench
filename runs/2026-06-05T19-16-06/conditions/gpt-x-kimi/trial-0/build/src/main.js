// ============================================
// Vanilla WebOS — Entry Point
// ============================================

window.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("#os-root");
  const os = new OS(root);

  // Expose for debugging
  window.webos = os;
  os.boot();
});
