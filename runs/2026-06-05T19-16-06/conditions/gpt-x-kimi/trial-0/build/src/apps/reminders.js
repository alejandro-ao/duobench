// ============================================
// Vanilla WebOS — Reminders App
// ============================================

class ReminderStore {
  constructor() {
    this.key = "webos.reminders";
    this.items = Storage.get(this.key, []);
  }

  save() {
    Storage.set(this.key, this.items);
  }

  add(title, dueAt) {
    this.items.push({
      id: IDs.generate(),
      title,
      dueAt,
      done: false,
      createdAt: Date.now()
    });
    this.save();
  }

  update(id, patch) {
    const item = this.items.find(x => x.id === id);
    if (item) {
      Object.assign(item, patch);
      this.save();
    }
  }

  delete(id) {
    this.items = this.items.filter(x => x.id !== id);
    this.save();
  }

  list() {
    return [...this.items].sort((a, b) => {
      if (a.done !== b.done) return a.done ? 1 : -1;
      return (a.dueAt || Infinity) - (b.dueAt || Infinity);
    });
  }
}

const RemindersApp = {
  id: "reminders",
  name: "Reminders",
  icon: "✅",
  category: "Productivity",
  defaultWidth: 520,
  defaultHeight: 540,
  minWidth: 320,
  minHeight: 300,

  create({ os }) {
    const store = new ReminderStore();

    const el = document.createElement("div");
    el.className = "app reminders";

    function render() {
      const items = store.list();

      el.innerHTML = `
        <div class="rm-toolbar">
          <input type="text" placeholder="New reminder..." data-input="title" />
          <input type="datetime-local" data-input="due" />
          <button data-action="add">Add</button>
        </div>
        <div class="rm-list">
          ${items.length === 0 ? `<div style="text-align:center;color:var(--muted);padding:40px;">No reminders yet</div>` :
            items.map(item => `
              <div class="rm-item ${item.done ? "is-done" : ""}" data-id="${item.id}">
                <input type="checkbox" ${item.done ? "checked" : ""} />
                <div class="rm-info">
                  <div class="rm-title">${escapeHtml(item.title)}</div>
                  <div class="rm-due">${item.dueAt ? DOM.formatDate(item.dueAt) : "No due date"}</div>
                </div>
                <button class="rm-delete">Delete</button>
              </div>
            `).join("")}
        </div>
      `;

      bind();
    }

    function bind() {
      const titleIn = el.querySelector('[data-input="title"]');
      const dueIn = el.querySelector('[data-input="due"]');

      el.querySelector("[data-action='add']").onclick = () => {
        const title = titleIn.value.trim();
        if (!title) return;
        const due = dueIn.value ? new Date(dueIn.value).getTime() : null;
        store.add(title, due);
        titleIn.value = "";
        dueIn.value = "";
        render();
      };

      el.querySelectorAll(".rm-item").forEach(row => {
        const id = row.dataset.id;
        const cb = row.querySelector("input[type='checkbox']");
        const del = row.querySelector(".rm-delete");

        cb.onchange = () => {
          store.update(id, { done: cb.checked });
          render();
        };

        del.onclick = () => {
          store.delete(id);
          render();
        };
      });
    }

    render();
    return { el };
  }
};

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
