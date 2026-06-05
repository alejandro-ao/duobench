// ============================================
// Vanilla WebOS — Text Editor App
// ============================================

const TextEditorApp = {
  id: "text-editor",
  name: "Text Editor",
  icon: "📝",
  category: "Productivity",
  defaultWidth: 700,
  defaultHeight: 500,
  minWidth: 320,
  minHeight: 240,

  create({ os, options }) {
    let path = options?.path || null;
    let dirty = false;

    const el = document.createElement("div");
    el.className = "app text-editor";
    el.innerHTML = `
      <div class="editor-toolbar">
        <button data-action="save">💾 Save</button>
        <button data-action="save-as">Save As</button>
        <span class="editor-path">${escapeHtml(path || "Untitled")}</span>
      </div>
      <textarea class="editor-area" spellcheck="false" placeholder="Start typing..."></textarea>
    `;

    const textarea = el.querySelector("textarea");
    const pathLabel = el.querySelector(".editor-path");

    if (path) {
      try {
        textarea.value = os.fs.readFile(path);
      } catch (err) {
        textarea.value = "";
      }
    }

    textarea.oninput = () => {
      dirty = true;
      updateTitle();
    };

    function updateTitle() {
      const name = path ? path.split("/").pop() : "Untitled";
      pathLabel.textContent = (dirty ? "● " : "") + name;
    }

    function doSave(newPath) {
      const target = newPath || path;
      if (!target) return;
      os.fs.writeFile(target, textarea.value);
      path = target;
      dirty = false;
      updateTitle();
      os.notifications.push({ title: "Text Editor", body: `Saved ${path.split("/").pop()}` });
    }

    el.querySelector("[data-action='save']").onclick = () => {
      if (!path) {
        const p = prompt("Save as", "/Documents/untitled.txt");
        if (p) doSave(p);
      } else {
        doSave();
      }
    };

    el.querySelector("[data-action='save-as']").onclick = () => {
      const p = prompt("Save as", path || "/Documents/untitled.txt");
      if (p) doSave(p);
    };

    // Keyboard shortcut Ctrl+S
    textarea.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (!path) {
          const p = prompt("Save as", "/Documents/untitled.txt");
          if (p) doSave(p);
        } else {
          doSave();
        }
      }
    });

    return {
      el,
      onClose() {
        if (dirty) return confirm("You have unsaved changes. Close anyway?");
        return true;
      }
    };
  }
};

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
