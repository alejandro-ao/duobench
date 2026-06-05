// ============================================
// Vanilla WebOS — Settings App
// ============================================

const SettingsApp = {
  id: "settings",
  name: "Settings",
  icon: "⚙️",
  category: "System",
  defaultWidth: 560,
  defaultHeight: 600,
  minWidth: 360,
  minHeight: 400,

  create({ os }) {
    const el = document.createElement("div");
    el.className = "app settings";

    const wallpapers = [
      { id: "gradient-1", label: "Midnight", value: "assets/wallpapers/gradient-1.jpg" },
      { id: "gradient-2", label: "Deep Space", value: "assets/wallpapers/gradient-2.jpg" },
      { id: "gradient-3", label: "Ocean", value: "assets/wallpapers/gradient-3.jpg" }
    ];

    function render() {
      const s = os.settings.all();

      el.innerHTML = `
        <div class="settings-section">
          <h3>Appearance</h3>
          <div class="settings-row">
            <label>Theme</label>
            <select data-setting="theme">
              <option value="dark" ${s.theme === "dark" ? "selected" : ""}>Dark</option>
              <option value="light" ${s.theme === "light" ? "selected" : ""}>Light</option>
            </select>
          </div>
          <div class="settings-row">
            <label>Accent Color</label>
            <input type="color" data-setting="accent" value="${s.accent}" />
          </div>
          <div class="settings-row">
            <label>Wallpaper</label>
          </div>
          <div class="wallpaper-grid">
            ${wallpapers.map(w => `
              <div class="wallpaper-option ${s.wallpaper === w.value ? "is-selected" : ""}"
                   data-wallpaper="${w.value}"
                   style="background: var(--panel-solid);"
                   title="${w.label}">
              </div>
            `).join("")}
          </div>
        </div>

        <div class="settings-section">
          <h3>Taskbar</h3>
          <div class="settings-row">
            <label>Alignment</label>
            <select data-setting="taskbarAlign">
              <option value="left" ${s.taskbarAlign === "left" ? "selected" : ""}>Left</option>
              <option value="center" ${s.taskbarAlign === "center" ? "selected" : ""}>Center</option>
              <option value="right" ${s.taskbarAlign === "right" ? "selected" : ""}>Right</option>
            </select>
          </div>
        </div>

        <div class="settings-section">
          <h3>System</h3>
          <div class="settings-row">
            <label>Reduce Motion</label>
            <input type="checkbox" data-setting="reduceMotion" ${s.reduceMotion ? "checked" : ""} />
          </div>
        </div>

        <div class="settings-section">
          <h3>Data</h3>
          <div class="settings-row">
            <label>Reset all data</label>
            <button class="settings-danger" data-action="reset">Reset to Defaults</button>
          </div>
        </div>
      `;

      // Wallpaper gradient previews
      const grads = [
        "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
        "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)",
        "linear-gradient(135deg, #1e3c72 0%, #2a5298 50%, #1e3c72 100%)"
      ];
      el.querySelectorAll(".wallpaper-option").forEach((opt, i) => {
        opt.style.background = grads[i];
      });

      bind();
    }

    function bind() {
      el.querySelectorAll("[data-setting]").forEach(input => {
        const key = input.dataset.setting;
        input.addEventListener("change", () => {
          const value = input.type === "checkbox" ? input.checked : input.value;
          os.settings.set(key, value);
        });
      });

      el.querySelectorAll("[data-wallpaper]").forEach(opt => {
        opt.onclick = () => {
          os.settings.set("wallpaper", opt.dataset.wallpaper);
          render();
        };
      });

      el.querySelector("[data-action='reset']").onclick = () => {
        if (confirm("This will erase all files, settings, and app data. Continue?")) {
          Storage.clear();
          location.reload();
        }
      };
    }

    render();
    return { el };
  }
};
