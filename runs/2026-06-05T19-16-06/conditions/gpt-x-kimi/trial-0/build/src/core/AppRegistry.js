// ============================================
// Vanilla WebOS — AppRegistry
// ============================================

class AppRegistry {
  constructor(os) {
    this.os = os;
    /** @type {Map<string, object>} */
    this.apps = new Map();
  }

  register(app) {
    this.apps.set(app.id, app);
  }

  get(appId) {
    return this.apps.get(appId);
  }

  list() {
    return [...this.apps.values()];
  }

  launch(appId, launchOptions = {}) {
    const app = this.get(appId);
    if (!app) throw new Error(`Unknown app: ${appId}`);

    const instance = app.create({
      os: this.os,
      app,
      options: launchOptions
    });

    const win = this.os.windowManager.createWindow({
      appId,
      title: app.name,
      icon: app.icon,
      width: app.defaultWidth || 700,
      height: app.defaultHeight || 500,
      minWidth: app.minWidth || 320,
      minHeight: app.minHeight || 240,
      content: instance.el,
      instance
    });

    if (instance.onMount) instance.onMount(win);

    this.os.events.emit("app:launched", { app, win });
    return win;
  }

  registerBuiltIns() {
    const builtins = [
      FileManagerApp,
      TextEditorApp,
      CalculatorApp,
      RemindersApp,
      SettingsApp,
      SnakeApp,
      TetrisApp,
      MinesweeperApp
    ];
    builtins.forEach(app => this.register(app));
  }
}
