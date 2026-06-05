// ============================================
// Vanilla WebOS — Calculator App
// ============================================

class CalculatorEngine {
  constructor() {
    this.history = Storage.get("webos.calc.history", []);
  }

  calculate(expr) {
    // Allow: digits, operators, parentheses, spaces, and common math functions
    const safe = expr.replace(/[^0-9+\-*/().\s^Mathsqrtpicosintaengl]/g, "");
    if (!safe.trim()) throw new Error("Empty expression");
    // Replace ^ with ** for exponentiation
    const jsExpr = safe.replace(/\^/g, "**");
    const result = Function(`"use strict"; return (${jsExpr})`)();
    this.history.unshift({ expr, result, at: Date.now() });
    this.history = this.history.slice(0, 50);
    Storage.set("webos.calc.history", this.history);
    return result;
  }
}

const CalculatorApp = {
  id: "calculator",
  name: "Calculator",
  icon: "🧮",
  category: "Utilities",
  defaultWidth: 520,
  defaultHeight: 560,
  minWidth: 300,
  minHeight: 400,

  create({ os }) {
    const engine = new CalculatorEngine();
    let expr = "";
    let result = "";
    let error = false;

    const el = document.createElement("div");
    el.className = "app calculator";

    function render() {
      el.innerHTML = `
        <div class="calc-display">
          <div class="calc-expr">${escapeHtml(expr)}</div>
          <div class="calc-result">${error ? "Error" : escapeHtml(String(result))}</div>
        </div>
        <div class="calc-body">
          <div class="calc-pad">
            ${[
              ["C","CE","⌫","/"],
              ["7","8","9","*"],
              ["4","5","6","-"],
              ["1","2","3","+"],
              ["0",".","^","="],
              ["(",")","sqrt","π"]
            ].map(row => row.map(k => {
              let cls = "";
              if (["/","*","-","+","^"].includes(k)) cls = "calc-op";
              if (k === "=") cls = "calc-eq";
              return `<button data-key="${k}" class="${cls}">${escapeHtml(k)}</button>`;
            }).join("")).join("")}
          </div>
          <div class="calc-history">
            <h4>History</h4>
            <div class="calc-history-list">
              ${engine.history.length === 0 ? `<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px;">No history</div>` :
                engine.history.map(h => `
                  <div class="calc-history-item" data-expr="${escapeHtml(h.expr)}">
                    <div class="chexpr">${escapeHtml(h.expr)}</div>
                    <div class="chres">= ${escapeHtml(String(h.result))}</div>
                  </div>
                `).join("")}
            </div>
          </div>
        </div>
      `;

      bind();
    }

    function bind() {
      el.querySelectorAll(".calc-pad button").forEach(btn => {
        btn.onclick = () => handleKey(btn.dataset.key);
      });

      el.querySelectorAll(".calc-history-item").forEach(item => {
        item.onclick = () => {
          expr = item.dataset.expr;
          result = "";
          error = false;
          render();
        };
      });
    }

    function handleKey(key) {
      if (key === "C") {
        expr = "";
        result = "";
        error = false;
      } else if (key === "CE") {
        expr = "";
        error = false;
      } else if (key === "⌫") {
        expr = expr.slice(0, -1);
        error = false;
      } else if (key === "=") {
        try {
          result = engine.calculate(expr);
          error = false;
        } catch {
          error = true;
        }
      } else if (key === "sqrt") {
        expr += "Math.sqrt(";
        error = false;
      } else if (key === "π") {
        expr += "Math.PI";
        error = false;
      } else {
        expr += key;
        error = false;
      }
      render();
    }

    // Keyboard support
    el.tabIndex = 0;
    el.addEventListener("keydown", (e) => {
      const key = e.key;
      if (/^[0-9+\-*/().^]$/.test(key)) {
        e.preventDefault();
        handleKey(key);
      } else if (key === "Enter") {
        e.preventDefault();
        handleKey("=");
      } else if (key === "Backspace") {
        e.preventDefault();
        handleKey("⌫");
      } else if (key === "Escape") {
        e.preventDefault();
        handleKey("C");
      }
    });

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
