// ============================================
// Vanilla WebOS — Virtual FileSystem
// ============================================

class FileSystem {
  constructor() {
    this.storageKey = "webos.fs";
    this.root = this.createDefaultFS();
  }

  createDefaultFS() {
    return {
      type: "folder",
      name: "root",
      children: {
        Desktop: { type: "folder", name: "Desktop", children: {}, createdAt: Date.now(), modifiedAt: Date.now() },
        Documents: { type: "folder", name: "Documents", children: {}, createdAt: Date.now(), modifiedAt: Date.now() },
        Downloads: { type: "folder", name: "Downloads", children: {}, createdAt: Date.now(), modifiedAt: Date.now() }
      },
      createdAt: Date.now(),
      modifiedAt: Date.now()
    };
  }

  load() {
    const raw = localStorage.getItem(this.storageKey);
    if (raw) {
      try { this.root = JSON.parse(raw); } catch { /* ignore corrupt */ }
    }
  }

  save() {
    localStorage.setItem(this.storageKey, JSON.stringify(this.root));
  }

  resolve(path) {
    const parts = path.split("/").filter(Boolean);
    let node = this.root;
    for (const part of parts) {
      if (!node.children || !node.children[part]) {
        throw new Error(`Path not found: ${path}`);
      }
      node = node.children[part];
    }
    return node;
  }

  list(path = "/") {
    const node = this.resolve(path);
    if (node.type !== "folder") throw new Error("Not a folder");
    return Object.values(node.children);
  }

  mkdir(path, name) {
    const folder = this.resolve(path);
    if (folder.type !== "folder") throw new Error("Not a folder");
    if (folder.children[name]) throw new Error("Already exists");
    folder.children[name] = {
      type: "folder",
      name,
      children: {},
      createdAt: Date.now(),
      modifiedAt: Date.now()
    };
    this.save();
  }

  writeFile(path, content, mime = "text/plain") {
    const parts = path.split("/").filter(Boolean);
    const name = parts.pop();
    const parent = this.resolve("/" + parts.join("/"));
    if (parent.type !== "folder") throw new Error("Not a folder");
    const now = Date.now();
    if (parent.children[name]) {
      parent.children[name].content = content;
      parent.children[name].mime = mime;
      parent.children[name].modifiedAt = now;
    } else {
      parent.children[name] = {
        type: "file",
        name,
        content,
        mime,
        createdAt: now,
        modifiedAt: now
      };
    }
    this.save();
  }

  readFile(path) {
    const node = this.resolve(path);
    if (node.type !== "file") throw new Error("Not a file");
    return node.content;
  }

  delete(path) {
    const parts = path.split("/").filter(Boolean);
    const name = parts.pop();
    const parent = this.resolve("/" + parts.join("/"));
    if (parent.type !== "folder") throw new Error("Not a folder");
    delete parent.children[name];
    this.save();
  }

  rename(path, newName) {
    const parts = path.split("/").filter(Boolean);
    const oldName = parts.pop();
    const parent = this.resolve("/" + parts.join("/"));
    if (parent.type !== "folder") throw new Error("Not a folder");
    const node = parent.children[oldName];
    if (!node) throw new Error("Not found");
    delete parent.children[oldName];
    node.name = newName;
    node.modifiedAt = Date.now();
    parent.children[newName] = node;
    this.save();
  }

  exists(path) {
    try { this.resolve(path); return true; } catch { return false; }
  }

  getNode(path) {
    return this.resolve(path);
  }
}
