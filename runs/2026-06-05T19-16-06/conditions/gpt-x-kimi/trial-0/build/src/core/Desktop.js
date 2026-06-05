// ============================================
// Vanilla WebOS — Desktop
// ============================================

class Desktop {
  constructor(os) {
    this.os = os;
    this.el = document.querySelector("#desktop");
    this.selectedIcon = null;
  }

  mount() {
    this.render();
    this.bindEvents();
  }

  render() {
    DOM.empty(this.el);

    const grid = DOM.create("div", { className: "desktop-icons", parent: this.el });

    // Add app shortcuts
    const apps = this.os.registry.list().filter(a => a.showOnDesktop !== false);
    apps.forEach(app => {
      const icon = DOM.create("div", { className: "desktop-icon", parent: grid });
      icon.innerHTML = `
        <div class="icon-emoji">${app.icon}</div>
        <div class="icon-label">${escapeHtml(app.name)}</div>
      `;
      icon.onclick = () => {
        this.selectIcon(icon);
      };
      icon.ondblclick = () => {
        this.os.launchApp(app.id);
      };
    });
  }

  selectIcon(iconEl) {
    this.el.querySelectorAll(".desktop-icon").forEach(i => i.classList.remove("is-selected"));
    iconEl.classList.add("is-selected");
    this.selectedIcon = iconEl;
  }

  bindEvents() {
    // Desktop context menu
    this.el.addEventListener("contextmenu", e => {
      if (e.target.closest(".desktop-icon")) return;
      e.preventDefault();

      this.os.contextMenu.show(e.clientX, e.clientY, [
        { label: "New Folder", icon: "📁", action: () => {
          const name = prompt("Folder name", "New Folder");
          if (name) {
            this.os.fs.mkdir("/Desktop", name);
            this.os.notifications.push({ title: "Desktop", body: `Created folder "${name}"` });
          }
        }},
        "---",
        { label: "Open Settings", icon: "⚙️", action: () => this.os.launchApp("settings") },
        { label: "Refresh", icon: "🔄", action: () => this.render() }
      ]);
    });

    // Click empty space deselects
    this.el.addEventListener("click", e => {
      if (e.target === this.el || e.target.closest(".desktop-icons") === this.el.querySelector(".desktop-icons")) {
        this.el.querySelectorAll(".desktop-icon").forEach(i => i.classList.remove("is-selected"));
        this.selectedIcon = null;
      }
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
