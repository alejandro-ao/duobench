// ============================================
// Vanilla WebOS — OS (Central Coordinator)
// ============================================

class OS {
  constructor(root) {
    this.root = root;
    this.events = new EventBus();
    this.settings = new SettingsStore();
    this.fs = new FileSystem();
    this.notifications = new NotificationCenter(this.events);
    this.contextMenu = new ContextMenu();
    this.registry = new AppRegistry(this);
    this.windowManager = new WindowManager(this);
    this.desktop = new Desktop(this);
    this.taskbar = new Taskbar(this);
  }

  boot() {
    this.settings.load();
    this.fs.load();
    this.registry.registerBuiltIns();
    this.desktop.mount();
    this.taskbar.mount();
    this.applyTheme();

    // Listen for theme changes
    window.addEventListener("settings:changed", (e) => {
      if (e.detail.key === "theme" || e.detail.key === "accent" || e.detail.key === "wallpaper") {
        this.applyTheme();
      }
    });

    // Global keyboard shortcuts
    document.addEventListener("keydown", (e) => {
      // Alt+F4 close focused window
      if (e.altKey && e.key === "F4") {
        const focused = this.windowManager.list().find(w => w.el.classList.contains("is-focused"));
        if (focused) {
          e.preventDefault();
          this.windowManager.close(focused.id);
        }
      }
    });

    this.notifications.push({
      title: "Welcome",
      body: "Vanilla WebOS is ready. Open the Start Menu to explore apps."
    });
  }

  launchApp(appId, options = {}) {
    return this.registry.launch(appId, options);
  }

  applyTheme() {
    const theme = this.settings.get("theme", "dark");
    const accent = this.settings.get("accent", "#7c3aed");
    const wallpaper = this.settings.get("wallpaper", "");

    document.documentElement.dataset.theme = theme;
    document.documentElement.style.setProperty("--accent", accent);

    const desktop = document.querySelector("#desktop");
    if (wallpaper) {
      // Use SVG wallpapers if path points to our assets
      if (wallpaper.startsWith("assets/wallpapers/gradient-")) {
        const num = wallpaper.match(/gradient-(\d)/)?.[1] || "1";
        desktop.className = "";
        desktop.style.backgroundImage = `url("assets/wallpapers/gradient-${num}.svg")`;
      } else {
        desktop.className = "";
        desktop.style.backgroundImage = `url("${wallpaper}")`;
      }
    }
  }
}
