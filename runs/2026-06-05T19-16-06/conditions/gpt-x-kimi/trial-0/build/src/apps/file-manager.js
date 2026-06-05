// ============================================
// Vanilla WebOS — File Manager App
// ============================================

const FileManagerApp = {
  id: "file-manager",
  name: "File Manager",
  icon: "📁",
  category: "Utilities",
  defaultWidth: 850,
  defaultHeight: 560,
  minWidth: 400,
  minHeight: 300,

  create({ os }) {
    let currentPath = "/";
    let selectedItem = null;

    const el = document.createElement("div");
    el.className = "app file-manager";

    function render() {
      let items = [];
      try {
        items = os.fs.list(currentPath);
      } catch {
        currentPath = "/";
        items = os.fs.list(currentPath);
      }

      el.innerHTML = `
        <div class="fm-toolbar">
          <button data-action="up">⬆ Up</button>
          <div class="breadcrumbs">${escapeHtml(currentPath) || "/"}</div>
          <button data-action="new-folder">📁 New Folder</button>
          <button data-action="new-file">📄 New File</button>
        </div>
        <div class="fm-body">
          <aside class="fm-tree"></aside>
          <main class="fm-list"></main>
        </div>
      `;

      renderTree();
      renderList(items);
      bind();
    }

    function renderTree() {
      const tree = el.querySelector(".fm-tree");
      if (!tree) return;

      const folders = ["/Desktop", "/Documents", "/Downloads"];
      tree.innerHTML = folders.map(f => {
        const isActive = currentPath === f;
        return `<div class="fm-tree-item ${isActive ? "is-active" : ""}" data-path="${f}">
          📁 ${escapeHtml(f.replace("/", ""))}
        </div>`;
      }).join("");

      tree.querySelectorAll(".fm-tree-item").forEach(item => {
        item.onclick = () => {
          currentPath = item.dataset.path;
          render();
        };
      });
    }

    function renderList(items) {
      const list = el.querySelector(".fm-list");
      if (!list) return;

      if (items.length === 0) {
        list.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--muted);padding:40px;">Empty folder</div>`;
        return;
      }

      list.innerHTML = items.map(item => `
        <div class="fm-item" data-name="${escapeHtml(item.name)}" data-type="${item.type}">
          <div>${item.type === "folder" ? "📁" : "📄"}</div>
          <span>${escapeHtml(item.name)}</span>
        </div>
      `).join("");

      list.querySelectorAll(".fm-item").forEach(itemEl => {
        itemEl.onclick = () => {
          list.querySelectorAll(".fm-item").forEach(i => i.classList.remove("is-selected"));
          itemEl.classList.add("is-selected");
          selectedItem = { name: itemEl.dataset.name, type: itemEl.dataset.type };
        };

        itemEl.ondblclick = () => {
          const name = itemEl.dataset.name;
          const type = itemEl.dataset.type;
          const path = normalizePath(`${currentPath}/${name}`);

          if (type === "folder") {
            currentPath = path;
            render();
          } else {
            os.launchApp("text-editor", { path });
          }
        };

        itemEl.oncontextmenu = (e) => {
          e.preventDefault();
          e.stopPropagation();
          const name = itemEl.dataset.name;
          const type = itemEl.dataset.type;
          const path = normalizePath(`${currentPath}/${name}`);

          os.contextMenu.show(e.clientX, e.clientY, [
            { label: type === "folder" ? "Open" : "Edit", icon: "📂", action: () => {
              if (type === "folder") { currentPath = path; render(); }
              else { os.launchApp("text-editor", { path }); }
            }},
            { label: "Rename", icon: "✏️", action: () => {
              const newName = prompt("Rename to", name);
              if (newName && newName !== name) {
                os.fs.rename(path, newName);
                render();
              }
            }},
            "---",
            { label: "Delete", icon: "🗑️", action: () => {
              if (confirm(`Delete "${name}"?`)) {
                os.fs.delete(path);
                render();
              }
            }}
          ]);
        };
      });
    }

    function bind() {
      el.querySelector("[data-action='up']").onclick = () => {
        if (currentPath === "/") return;
        const parts = currentPath.split("/").filter(Boolean);
        parts.pop();
        currentPath = "/" + parts.join("/");
        render();
      };

      el.querySelector("[data-action='new-folder']").onclick = () => {
        const name = prompt("Folder name", "New Folder");
        if (name) {
          try { os.fs.mkdir(currentPath, name); } catch (err) { alert(err.message); }
          render();
        }
      };

      el.querySelector("[data-action='new-file']").onclick = () => {
        const name = prompt("File name", "untitled.txt");
        if (name) {
          const path = normalizePath(`${currentPath}/${name}`);
          os.fs.writeFile(path, "");
          render();
        }
      };
    }

    render();

    return { el };
  }
};

function normalizePath(path) {
  return path.replace(/\/+/g, "/");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
