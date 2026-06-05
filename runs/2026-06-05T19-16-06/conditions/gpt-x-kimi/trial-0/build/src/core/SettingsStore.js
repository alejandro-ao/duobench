// ============================================
// Vanilla WebOS — SettingsStore
// ============================================

class SettingsStore {
  constructor() {
    this.key = "webos.settings";
    this.state = {
      theme: "dark",
      accent: "#7c3aed",
      wallpaper: "assets/wallpapers/gradient-1.jpg",
      reduceMotion: false,
      taskbarAlign: "center",
      desktopIconSize: "medium",
      pins: ["file-manager", "text-editor", "calculator"]
    };
  }

  load() {
    const saved = Storage.get(this.key, {});
    Object.assign(this.state, saved);
  }

  save() {
    Storage.set(this.key, this.state);
  }

  get(key, fallback) {
    return this.state[key] ?? fallback;
  }

  set(key, value) {
    this.state[key] = value;
    this.save();
    window.dispatchEvent(new CustomEvent("settings:changed", { detail: { key, value } }));
  }

  all() {
    return { ...this.state };
  }
}
