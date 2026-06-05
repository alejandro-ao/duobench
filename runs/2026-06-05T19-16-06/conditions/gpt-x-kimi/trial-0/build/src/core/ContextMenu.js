// ============================================
// Vanilla WebOS — ContextMenu Service
// ============================================

class ContextMenu {
  constructor() {
    this.el = document.createElement("div");
    this.el.className = "context-menu";
    document.body.appendChild(this.el);

    this._hideOnClick = (e) => {
      if (!this.el.contains(e.target)) this.hide();
    };
    document.addEventListener("click", this._hideOnClick);
    document.addEventListener("scroll", () => this.hide(), true);
  }

  show(x, y, items) {
    this.el.innerHTML = items.map((item, i) => {
      if (item === "---") return `<div class="separator"></div>`;
      return `
        <button data-index="${i}" ${item.disabled ? "disabled" : ""}>
          <span>${item.icon || ""}</span>
          <span>${item.label}</span>
        </button>
      `;
    }).join("");

    this.el.querySelectorAll("button").forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const idx = Number(btn.dataset.index);
        const item = items[idx];
        if (item && item.action) item.action();
        this.hide();
      };
    });

    Object.assign(this.el.style, {
      left: `${x}px`,
      top: `${y}px`,
      display: "flex"
    });

    // Keep inside viewport
    requestAnimationFrame(() => {
      const rect = this.el.getBoundingClientRect();
      if (rect.right > window.innerWidth) {
        this.el.style.left = `${window.innerWidth - rect.width - 8}px`;
      }
      if (rect.bottom > window.innerHeight) {
        this.el.style.top = `${window.innerHeight - rect.height - 8}px`;
      }
    });
  }

  hide() {
    this.el.style.display = "none";
  }
}
