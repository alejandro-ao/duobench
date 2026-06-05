// ============================================
// Vanilla WebOS — WindowManager
// ============================================

class WindowManager {
  constructor(os) {
    this.os = os;
    this.windows = new Map();
    this.z = 100;
    this.container = document.querySelector("#window-layer");
  }

  createWindow(config) {
    const win = new OSWindow(this, config);
    this.windows.set(win.id, win);
    this.container.appendChild(win.el);

    this.focus(win.id);
    this.os.taskbar.addWindow(win);
    this.os.events.emit("window:created", win);

    // Small screen: maximize by default
    if (window.innerWidth < 700) {
      win.toggleMaximize();
    }

    return win;
  }

  focus(id) {
    const win = this.windows.get(id);
    if (!win) return;

    this.z += 1;
    win.el.style.zIndex = this.z;

    this.windows.forEach(w => w.setFocused(false));
    win.setFocused(true);

    this.os.taskbar.setActive(id);
    this.os.events.emit("window:focused", win);
  }

  close(id) {
    const win = this.windows.get(id);
    if (!win) return;

    if (win.instance?.onClose) {
      const shouldClose = win.instance.onClose();
      if (shouldClose === false) return;
    }

    win.destroy();
    this.windows.delete(id);
    this.os.taskbar.removeWindow(id);
    this.os.events.emit("window:closed", win);
  }

  minimize(id) {
    const win = this.windows.get(id);
    if (!win) return;
    win.minimize();
    this.os.taskbar.setMinimized(id, true);
  }

  restore(id) {
    const win = this.windows.get(id);
    if (!win) return;
    win.restore();
    this.focus(id);
    this.os.taskbar.setMinimized(id, false);
  }

  maximize(id) {
    const win = this.windows.get(id);
    if (!win) return;
    win.toggleMaximize();
    this.focus(id);
  }

  get(id) {
    return this.windows.get(id);
  }

  list() {
    return [...this.windows.values()];
  }
}
