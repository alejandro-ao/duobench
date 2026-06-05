// ============================================
// Vanilla WebOS — Minesweeper Game
// ============================================

const MINESWEEPER_PRESETS = {
  easy:   { cols: 9,  rows: 9,  mines: 10 },
  medium: { cols: 16, rows: 16, mines: 40 },
  hard:   { cols: 30, rows: 16, mines: 99 }
};

class MinesweeperEngine {
  constructor(cols, rows, mines) {
    this.cols = cols;
    this.rows = rows;
    this.mines = mines;
    this.reset();
  }

  reset() {
    this.board = Array.from({ length: this.rows }, () =>
      Array.from({ length: this.cols }, () => ({
        mine: false,
        revealed: false,
        flagged: false,
        adjacent: 0
      }))
    );
    this.gameOver = false;
    this.won = false;
    this.firstClick = true;
    this.flags = 0;
  }

  placeMines(safeX, safeY) {
    let placed = 0;
    while (placed < this.mines) {
      const x = Math.floor(Math.random() * this.cols);
      const y = Math.floor(Math.random() * this.rows);
      if (Math.abs(x - safeX) <= 1 && Math.abs(y - safeY) <= 1) continue;
      if (!this.board[y][x].mine) {
        this.board[y][x].mine = true;
        placed++;
      }
    }

    for (let y = 0; y < this.rows; y++) {
      for (let x = 0; x < this.cols; x++) {
        if (this.board[y][x].mine) continue;
        let count = 0;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const ny = y + dy, nx = x + dx;
            if (ny >= 0 && ny < this.rows && nx >= 0 && nx < this.cols && this.board[ny][nx].mine) {
              count++;
            }
          }
        }
        this.board[y][x].adjacent = count;
      }
    }
  }

  reveal(x, y) {
    if (this.gameOver) return;
    const cell = this.board[y][x];
    if (cell.revealed || cell.flagged) return;

    if (this.firstClick) {
      this.placeMines(x, y);
      this.firstClick = false;
    }

    cell.revealed = true;

    if (cell.mine) {
      this.gameOver = true;
      this.won = false;
      return;
    }

    if (cell.adjacent === 0) {
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const ny = y + dy, nx = x + dx;
          if (ny >= 0 && ny < this.rows && nx >= 0 && nx < this.cols) {
            this.reveal(nx, ny);
          }
        }
      }
    }

    this.checkWin();
  }

  toggleFlag(x, y) {
    if (this.gameOver) return;
    const cell = this.board[y][x];
    if (cell.revealed) return;
    cell.flagged = !cell.flagged;
    this.flags += cell.flagged ? 1 : -1;
    this.checkWin();
  }

  checkWin() {
    let unrevealedSafe = 0;
    for (let y = 0; y < this.rows; y++) {
      for (let x = 0; x < this.cols; x++) {
        const c = this.board[y][x];
        if (!c.revealed && !c.mine) unrevealedSafe++;
      }
    }
    if (unrevealedSafe === 0) {
      this.gameOver = true;
      this.won = true;
    }
  }
}

const MinesweeperApp = {
  id: "minesweeper",
  name: "Minesweeper",
  icon: "💣",
  category: "Games",
  defaultWidth: 540,
  defaultHeight: 620,
  minWidth: 320,
  minHeight: 400,

  create({ os }) {
    const el = document.createElement("div");
    el.className = "app game minesweeper-app";

    let difficulty = "easy";
    let engine = new MinesweeperEngine(9, 9, 10);
    let cellSize = 28;
    let canvas, ctx;
    let raf;

    function buildUI() {
      el.innerHTML = `
        <div class="game-toolbar">
          <button data-action="new">New Game</button>
          <select data-action="difficulty">
            <option value="easy" ${difficulty === "easy" ? "selected" : ""}>Easy</option>
            <option value="medium" ${difficulty === "medium" ? "selected" : ""}>Medium</option>
            <option value="hard" ${difficulty === "hard" ? "selected" : ""}>Hard</option>
          </select>
          <div class="game-stats">Mines: <span id="ms-mines">${engine.mines}</span> | Flags: <span id="ms-flags">0</span></div>
        </div>
        <canvas></canvas>
      `;

      canvas = el.querySelector("canvas");
      ctx = canvas.getContext("2d");

      resizeCanvas();
      bind();
      draw();
    }

    function resizeCanvas() {
      const preset = MINESWEEPER_PRESETS[difficulty];
      // Fit within window bounds
      const maxW = 480;
      const maxH = 480;
      cellSize = Math.min(Math.floor(maxW / preset.cols), Math.floor(maxH / preset.rows), 32);
      canvas.width = preset.cols * cellSize;
      canvas.height = preset.rows * cellSize;
    }

    function bind() {
      el.querySelector("[data-action='new']").onclick = () => {
        const preset = MINESWEEPER_PRESETS[difficulty];
        engine = new MinesweeperEngine(preset.cols, preset.rows, preset.mines);
        resizeCanvas();
        draw();
        updateStats();
      };

      el.querySelector("[data-action='difficulty']").onchange = (e) => {
        difficulty = e.target.value;
        const preset = MINESWEEPER_PRESETS[difficulty];
        engine = new MinesweeperEngine(preset.cols, preset.rows, preset.mines);
        resizeCanvas();
        draw();
        updateStats();
      };

      canvas.addEventListener("pointerdown", (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = Math.floor((e.clientX - rect.left) / cellSize);
        const y = Math.floor((e.clientY - rect.top) / cellSize);
        if (x < 0 || x >= engine.cols || y < 0 || y >= engine.rows) return;

        if (e.button === 2 || (e.pointerType === "touch" && e.shiftKey)) {
          engine.toggleFlag(x, y);
        } else {
          engine.reveal(x, y);
          if (engine.gameOver) {
            if (engine.won) {
              os.notifications.push({ title: "Minesweeper", body: "You won! 🎉" });
            } else {
              os.notifications.push({ title: "Minesweeper", body: "BOOM! Game Over 💥" });
            }
          }
        }
        updateStats();
        draw();
      });

      canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    }

    function updateStats() {
      const minesEl = el.querySelector("#ms-mines");
      const flagsEl = el.querySelector("#ms-flags");
      if (minesEl) minesEl.textContent = engine.mines;
      if (flagsEl) flagsEl.textContent = engine.flags;
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (let y = 0; y < engine.rows; y++) {
        for (let x = 0; x < engine.cols; x++) {
          const cell = engine.board[y][x];
          const cx = x * cellSize;
          const cy = y * cellSize;

          if (!cell.revealed) {
            ctx.fillStyle = "#2a2a3a";
            ctx.fillRect(cx, cy, cellSize, cellSize);
            ctx.strokeStyle = "#1f1f2e";
            ctx.strokeRect(cx, cy, cellSize, cellSize);
            if (cell.flagged) {
              ctx.fillStyle = "#ef4444";
              ctx.font = `${cellSize * 0.7}px system-ui`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillText("🚩", cx + cellSize / 2, cy + cellSize / 2);
            }
          } else {
            ctx.fillStyle = "#14141f";
            ctx.fillRect(cx, cy, cellSize, cellSize);
            ctx.strokeStyle = "#1f1f2e";
            ctx.strokeRect(cx, cy, cellSize, cellSize);

            if (cell.mine) {
              ctx.fillStyle = "#ef4444";
              ctx.beginPath();
              ctx.arc(cx + cellSize / 2, cy + cellSize / 2, cellSize * 0.3, 0, Math.PI * 2);
              ctx.fill();
            } else if (cell.adjacent > 0) {
              const colors = ["", "#3b82f6", "#22c55e", "#ef4444", "#a855f7", "#f97316", "#06b6d4", "#000", "#71717a"];
              ctx.fillStyle = colors[cell.adjacent] || "#fff";
              ctx.font = `bold ${cellSize * 0.6}px system-ui`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillText(String(cell.adjacent), cx + cellSize / 2, cy + cellSize / 2);
            }
          }
        }
      }

      if (engine.gameOver && !engine.won) {
        // Reveal all mines
        for (let y = 0; y < engine.rows; y++) {
          for (let x = 0; x < engine.cols; x++) {
            const cell = engine.board[y][x];
            if (cell.mine && !cell.revealed) {
              const cx = x * cellSize;
              const cy = y * cellSize;
              ctx.fillStyle = "#ef4444";
              ctx.beginPath();
              ctx.arc(cx + cellSize / 2, cy + cellSize / 2, cellSize * 0.3, 0, Math.PI * 2);
              ctx.fill();
            }
          }
        }
      }

      if (engine.gameOver) {
        ctx.fillStyle = "rgba(0,0,0,0.6)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#fff";
        ctx.font = "bold 22px system-ui";
        ctx.textAlign = "center";
        ctx.fillText(engine.won ? "You Win! 🎉" : "Game Over", canvas.width / 2, canvas.height / 2);
      }
    }

    buildUI();

    return {
      el,
      onUnmount() {
        cancelAnimationFrame(raf);
      }
    };
  }
};
