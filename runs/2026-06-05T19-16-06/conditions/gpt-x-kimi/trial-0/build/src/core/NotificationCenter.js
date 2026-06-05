// ============================================
// Vanilla WebOS — NotificationCenter
// ============================================

class NotificationCenter {
  constructor(events) {
    this.events = events;
    this.notifications = [];
    this.max = 100;
  }

  push({ title, body, icon = "🔔" }) {
    const n = {
      id: IDs.generate(),
      title,
      body,
      icon,
      at: Date.now()
    };
    this.notifications.unshift(n);
    if (this.notifications.length > this.max) {
      this.notifications.pop();
    }
    this.events.emit("notification:pushed", n);
    this.showToast(n);
    return n;
  }

  showToast(n) {
    const toast = document.createElement("div");
    toast.className = "notification-toast";
    toast.innerHTML = `
      <h4>${escapeHtml(n.title)}</h4>
      <p>${escapeHtml(n.body)}</p>
    `;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.classList.add("is-leaving");
      toast.addEventListener("animationend", () => toast.remove());
    }, 4000);
  }

  list() {
    return [...this.notifications];
  }

  clear() {
    this.notifications = [];
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
