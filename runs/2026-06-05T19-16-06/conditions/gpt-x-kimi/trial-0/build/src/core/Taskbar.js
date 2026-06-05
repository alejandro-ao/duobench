// ============================================
// Vanilla WebOS — Taskbar
// ============================================

class Taskbar {
  constructor(os) {
    this.os = os;
    this.el = document.querySelector("#taskbar");
    this.windows = new Map();
    this.startMenuOpen = false;
  }

  mount() {
    this.el.innerHTML = `
      <button id="start-button" aria-label="Start">⊞</button>
      <div id="quick-launch"></div>
      <div id="taskbar-windows"></div>
      <div id="system-tray">
        <button id="notifications-button" aria-label="Notifications">🔔</button>
        <span id="clock"></span>
      </div>
    `;

    this.bindStartMenu();
    this.renderPins();
    this.startClock();
    this.bindNotifications();

    // Listen for settings changes to re-render pins
    window.addEventListener("settings:changed", () => this.renderPins());
  }

  addWindow(win) {
    this.windows.set(win.id, win);
    this.renderWindows();
  }

  removeWindow(id) {
    this.windows.delete(id);
    this.renderWindows();
  }

  setActive(id) {
    document.querySelectorAll(".taskbar-window").forEach(btn => {
      btn.classList.toggle("is-active", btn.dataset.id === id);
    });
  }

  setMinimized(id, minimized) {
    const btn = document.querySelector(`.taskbar-window[data-id="${id}"]`);
    if (btn) btn.classList.toggle("is-minimized", minimized);
  }

  renderWindows() {
    const area = this.el.querySelector("#taskbar-windows");
    if (!area) return;

    area.innerHTML = [...this.windows.values()].map(win => `
      <button class="taskbar-window" data-id="${win.id}" title="${escapeHtml(win.title)}">
        <span>${win.icon}</span>
        <span>${escapeHtml(win.title)}</span>
      </button>
    `).join("");

    area.querySelectorAll(".taskbar-window").forEach(btn => {
      btn.onclick = () => {
        const win = this.windows.get(btn.dataset.id);
        if (!win) return;
        if (win.isMinimized) this.os.windowManager.restore(win.id);
        else if (win.el.classList.contains("is-focused")) this.os.windowManager.minimize(win.id);
        else this.os.windowManager.focus(win.id);
      };
    });
  }

  bindStartMenu() {
    const btn = this.el.querySelector("#start-button");
    btn.onclick = (e) => {
      e.stopPropagation();
      this.toggleStartMenu();
    };

    // Close start menu when clicking elsewhere
    document.addEventListener("click", (e) => {
      if (this.startMenuOpen && !this.startMenuEl.contains(e.target) && e.target !== btn) {
        this.closeStartMenu();
      }
    });
  }

  toggleStartMenu() {
    if (this.startMenuOpen) {
      this.closeStartMenu();
    } else {
      this.openStartMenu();
    }
  }

  openStartMenu() {
    if (!this.startMenuEl) {
      this.startMenuEl = document.createElement("div");
      this.startMenuEl.className = "start-menu";
      document.body.appendChild(this.startMenuEl);
    }

    const apps = this.os.registry.list().sort((a, b) => a.name.localeCompare(b.name));

    this.startMenuEl.innerHTML = `
      <div class="start-menu-header">Applications</div>
      <div class="start-menu-list">
        ${apps.map(app => `
          <div class="start-menu-item" data-app="${app.id}">
            <div class="smi-icon">${app.icon}</div>
            <div class="smi-name">${escapeHtml(app.name)}</div>
          </div>
        `).join("")}
      </div>
    `;

    this.startMenuEl.querySelectorAll(".start-menu-item").forEach(item => {
      item.onclick = () => {
        this.os.launchApp(item.dataset.app);
        this.closeStartMenu();
      };
    });

    this.startMenuEl.classList.add("is-open");
    this.startMenuOpen = true;
  }

  closeStartMenu() {
    if (this.startMenuEl) this.startMenuEl.classList.remove("is-open");
    this.startMenuOpen = false;
  }

  renderPins() {
    const area = this.el.querySelector("#quick-launch");
    if (!area) return;

    const pins = this.os.settings.get("pins", []);
    area.innerHTML = pins.map(id => {
      const app = this.os.registry.get(id);
      if (!app) return "";
      return `<button data-app="${app.id}" title="${escapeHtml(app.name)}">${app.icon}</button>`;
    }).join("");

    area.querySelectorAll("button").forEach(btn => {
      btn.onclick = () => this.os.launchApp(btn.dataset.app);
    });
  }

  startClock() {
    const clock = this.el.querySelector("#clock");
    if (!clock) return;

    const tick = () => {
      clock.textContent = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit"
      });
    };

    tick();
    setInterval(tick, 1000);
  }

  bindNotifications() {
    const btn = this.el.querySelector("#notifications-button");
    if (!btn) return;

    btn.onclick = (e) => {
      e.stopPropagation();
      this.toggleNotificationCenter();
    };

    this.os.events.on("notification:pushed", () => {
      btn.classList.add("has-unread");
    });
  }

  toggleNotificationCenter() {
    if (!this.ncEl) {
      this.ncEl = document.createElement("div");
      this.ncEl.className = "notification-center";
      document.body.appendChild(this.ncEl);

      this.ncEl.innerHTML = `
        <header>
          <h3>Notifications</h3>
          <button id="nc-clear" style="font-size:12px;padding:4px 10px;border-radius:6px;background:var(--panel-solid);border:1px solid var(--border);">Clear</button>
        </header>
        <div class="nc-list"></div>
      `;

      this.ncEl.querySelector("#nc-clear").onclick = () => {
        this.os.notifications.clear();
        this.renderNotificationCenter();
      };

      // Close when clicking outside
      document.addEventListener("click", (e) => {
        if (this.ncEl.classList.contains("is-open") && !this.ncEl.contains(e.target)) {
          this.ncEl.classList.remove("is-open");
          this.el.querySelector("#notifications-button").classList.remove("has-unread");
        }
      });
    }

    const isOpen = this.ncEl.classList.contains("is-open");
    if (isOpen) {
      this.ncEl.classList.remove("is-open");
    } else {
      this.renderNotificationCenter();
      this.ncEl.classList.add("is-open");
      this.el.querySelector("#notifications-button").classList.remove("has-unread");
    }
  }

  renderNotificationCenter() {
    const list = this.ncEl.querySelector(".nc-list");
    const notes = this.os.notifications.list();

    if (notes.length === 0) {
      list.innerHTML = `<div class="nc-empty">No notifications</div>`;
      return;
    }

    list.innerHTML = notes.map(n => `
      <div class="nc-item">
        <h5>${escapeHtml(n.title)}</h5>
        <p>${escapeHtml(n.body)}</p>
        <time>${DOM.timeAgo(n.at)}</time>
      </div>
    `).join("");
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
