// ============================================
// Vanilla WebOS — OSWindow
// ============================================

class OSWindow {
  constructor(manager, config) {
    this.manager = manager;
    this.id = IDs.generate();
    this.appId = config.appId;
    this.title = config.title;
    this.icon = config.icon;
    this.instance = config.instance;
    this.isMinimized = false;
    this.isMaximized = false;

    this.bounds = {
      x: 80 + Math.random() * 80,
      y: 60 + Math.random() * 60,
      width: config.width || 700,
      height: config.height || 500
    };

    this.minWidth = config.minWidth || 320;
    this.minHeight = config.minHeight || 240;

    this.previousBounds = null;
    this.el = this.render(config);
    this.applyBounds();
    this.bindEvents();
  }

  render(config) {
    const el = document.createElement("section");
    el.className = "os-window";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", config.title);
    el.innerHTML = `
      <header class="window-titlebar">
        <div class="window-title">
          <span>${config.icon}</span>
          <span>${escapeHtml(config.title)}</span>
        </div>
        <div class="window-controls">
          <button data-action="minimize" aria-label="Minimize">—</button>
          <button data-action="maximize" aria-label="Maximize">□</button>
          <button data-action="close" aria-label="Close">×</button>
        </div>
      </header>
      <main class="window-content"></main>
      <div class="resize-handle resize-se" aria-hidden="true"></div>
    `;

    el.querySelector(".window-content").appendChild(config.content);
    return el;
  }

  bindEvents() {
    this.el.addEventListener("mousedown", () => {
      this.manager.focus(this.id);
    });

    this.el.querySelector("[data-action='close']").onclick = () => {
      this.manager.close(this.id);
    };

    this.el.querySelector("[data-action='minimize']").onclick = () => {
      this.manager.minimize(this.id);
    };

    this.el.querySelector("[data-action='maximize']").onclick = () => {
      this.manager.maximize(this.id);
    };

    this.enableDrag();
    this.enableResize();
  }

  applyBounds() {
    Object.assign(this.el.style, {
      left: `${this.bounds.x}px`,
      top: `${this.bounds.y}px`,
      width: `${this.bounds.width}px`,
      height: `${this.bounds.height}px`
    });
  }

  setFocused(focused) {
    this.el.classList.toggle("is-focused", focused);
  }

  minimize() {
    this.isMinimized = true;
    this.el.classList.add("is-minimized");
  }

  restore() {
    this.isMinimized = false;
    this.el.classList.remove("is-minimized");
  }

  toggleMaximize() {
    if (this.isMaximized) {
      this.bounds = { ...this.previousBounds };
      this.isMaximized = false;
    } else {
      this.previousBounds = { ...this.bounds };
      this.bounds = {
        x: 0,
        y: 0,
        width: window.innerWidth,
        height: window.innerHeight - 48
      };
      this.isMaximized = true;
    }

    this.el.classList.toggle("is-maximized", this.isMaximized);
    this.applyBounds();
  }

  destroy() {
    this.instance?.onUnmount?.();
    this.el.remove();
  }

  enableDrag() {
    const bar = this.el.querySelector(".window-titlebar");

    bar.addEventListener("pointerdown", (e) => {
      if (this.isMaximized) return;
      if (e.target.closest(".window-controls")) return;

      const startX = e.clientX;
      const startY = e.clientY;
      const startBounds = { ...this.bounds };

      bar.setPointerCapture(e.pointerId);

      const move = (ev) => {
        this.bounds.x = startBounds.x + ev.clientX - startX;
        this.bounds.y = startBounds.y + ev.clientY - startY;
        this.bounds.x = Math.max(0, this.bounds.x);
        this.bounds.y = Math.max(0, this.bounds.y);
        this.applyBounds();
      };

      const up = () => {
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
      };

      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
    });
  }

  enableResize() {
    const handle = this.el.querySelector(".resize-se");

    handle.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      const startX = e.clientX;
      const startY = e.clientY;
      const startBounds = { ...this.bounds };

      handle.setPointerCapture(e.pointerId);

      const move = (ev) => {
        this.bounds.width = Math.max(this.minWidth, startBounds.width + ev.clientX - startX);
        this.bounds.height = Math.max(this.minHeight, startBounds.height + ev.clientY - startY);
        this.applyBounds();
      };

      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
      };

      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
