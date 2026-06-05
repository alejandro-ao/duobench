// ============================================
// Vanilla WebOS — Tetris Game
// ============================================

const TETROMINOES = {
  I: { shape: [[0,0,0,0],[1,1,1,1],[0,0,0,0],[0,0,0,0]], color: "#06b6d4" },
  O: { shape: [[1,1],[1,1]], color: "#eab308" },
  T: { shape: [[0,1,0],[1,1,1],[0,0,0]], color: "#a855f7" },
  S: { shape: [[0,1,1],[1,1,0],[0,0,0]], color: "#22c55e" },
  Z: { shape: [[1,1,0],[0,1,1],[0,0,0]], color: "#ef4444" },
  J: { shape: [[1,0,0],[1,1,1],[0,0,0]], color: "#3b82f6" },
  L: { shape: [[0,0,1],[1,1,1],[0,0,0]], color: "#f97316" }
};

class TetrisEngine {
  constructor() {
    this.cols = 10;
    this.rows = 20;
    this.reset();
  }

  reset() {
    this.board = this.createBoard();
    this.bag = [];
    this.queue = [];
    this.hold = null;
    this.canHold = true;
    this.score = 0;
    this.level = 1;
    this.lines = 0;
    this.current = this.nextPiece();
    this.gameOver = false;
    this.dropTimer = 0;
    this.dropInterval = 1000;
  }

  createBoard() {
    return Array.from({ length: this.rows }, () => Array(this.cols).fill(0));
  }

  nextPiece() {
    if (this.queue.length < 5) {
      this.fillQueue();
    }
    const type = this.queue.shift();
    const def = TETROMINOES[type];
    return {
      type,
      shape: def.shape.map(r => [...r]),
      color: def.color,
      x: Math.floor((this.cols - def.shape[0].length) / 2),
      y: 0
    };
  }

  fillQueue() {
    if (this.bag.length === 0) {
      this.bag = Object.keys(TETROMINOES).sort(() => Math.random() - 0.5);
    }
    while (this.bag.length > 0 && this.queue.length < 7) {
      this.queue.push(this.bag.pop());
    }
  }

  update(dt) {
    if (this.gameOver) return;
    this.dropTimer += dt;
    this.dropInterval = Math.max(100, 1000 - (this.level - 1) * 80);
    if (this.dropTimer >= this.dropInterval) {
      this.dropTimer = 0;
      if (!this.move(0, 1)) {
        this.lockPiece();
      }
    }
  }

  move(dx, dy) {
    if (this.collides(this.current, this.current.x + dx, this.current.y + dy)) return false;
    this.current.x += dx;
    this.current.y += dy;
    return true;
  }

  rotate() {
    const old = this.current.shape;
    const N = old.length;
    const rotated = Array.from({ length: N }, () => Array(N).fill(0));
    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        rotated[x][N - 1 - y] = old[y][x];
      }
    }
    const oldShape = this.current.shape;
    this.current.shape = rotated;
    if (this.collides(this.current, this.current.x, this.current.y)) {
      // Try wall kicks
      const kicks = [1, -1, 2, -2];
      for (const k of kicks) {
        if (!this.collides(this.current, this.current.x + k, this.current.y)) {
          this.current.x += k;
          return;
        }
      }
      this.current.shape = oldShape;
    }
  }

  softDrop() {
    if (this.move(0, 1)) {
      this.score += 1;
    }
  }

  hardDrop() {
    while (this.move(0, 1)) {
      this.score += 2;
    }
    this.lockPiece();
  }

  holdPiece() {
    if (!this.canHold) return;
    if (this.hold === null) {
      this.hold = this.current.type;
      this.current = this.nextPiece();
    } else {
      const temp = this.hold;
      this.hold = this.current.type;
      const def = TETROMINOES[temp];
      this.current = {
        type: temp,
        shape: def.shape.map(r => [...r]),
        color: def.color,
        x: Math.floor((this.cols - def.shape[0].length) / 2),
        y: 0
      };
    }
    this.canHold = false;
  }

  lockPiece() {
    const { shape, x, y, color } = this.current;
    for (let r = 0; r < shape.length; r++) {
      for (let c = 0; c < shape[r].length; c++) {
        if (shape[r][c]) {
          const by = y + r;
          const bx = x + c;
          if (by >= 0) this.board[by][bx] = color;
        }
      }
    }
    this.clearLines();
    this.current = this.nextPiece();
    this.canHold = true;
    if (this.collides(this.current, this.current.x, this.current.y)) {
      this.gameOver = true;
    }
  }

  clearLines() {
    let cleared = 0;
    for (let r = this.rows - 1; r >= 0; r--) {
      if (this.board[r].every(cell => cell !== 0)) {
        this.board.splice(r, 1);
        this.board.unshift(Array(this.cols).fill(0));
        cleared++;
        r++; // recheck same row
      }
    }
    if (cleared > 0) {
      const points = [0, 100, 300, 500, 800];
      this.score += points[cleared] * this.level;
      this.lines += cleared;
      this.level = Math.floor(this.lines / 10) + 1;
    }
  }

  collides(piece, px, py) {
    for (let r = 0; r < piece.shape.length; r++) {
      for (let c = 0; c < piece.shape[r].length; c++) {
        if (piece.shape[r][c]) {
          const x = px + c;
          const y = py + r;
          if (x < 0 || x >= this.cols || y >= this.rows) return true;
          if (y >= 0 && this.board[y][x]) return true;
        }
      }
    }
    return false;
  }

  getGhostY() {
    let gy = this.current.y;
    while (!this.collides(this.current, this.current.x, gy + 1)) {
      gy++;
    }
    return gy;
  }
}

const TetrisApp = {
  id: "tetris",
  name: "Tetris",
  icon: "🎮",
  category: "Games",
  defaultWidth: 640,
  defaultHeight: 640,
  minWidth: 400,
  minHeight: 500,

  create({ os }) {
    const el = document.createElement("div");
    el.className = "app game tetris-app";

    el.innerHTML = `
      <div class="tetris-main">
        <div class="game-toolbar">
          <button data-action="start">Start</button>
          <button data-action="pause">Pause</button>
        </div>
        <canvas width="300" height="600"></canvas>
      </div>
      <div class="tetris-side">
        <div class="tetris-box">
          <h5>Hold</h5>
          <canvas id="hold-canvas" width="80" height="80"></canvas>
        </div>
        <div class="tetris-box">
          <h5>Next</h5>
          <canvas id="next-canvas" width="80" height="80"></canvas>
        </div>
        <div class="tetris-box">
          <h5>Score</h5>
          <div class="tb-value" id="tetris-score">0</div>
        </div>
        <div class="tetris-box">
          <h5>Level</h5>
          <div class="tb-value" id="tetris-level">1</div>
        </div>
        <div class="tetris-box">
          <h5>Lines</h5>
          <div class="tb-value" id="tetris-lines">0</div>
        </div>
        <div class="tetris-box tetris-controls">
          ← → Move<br>↑ Rotate<br>↓ Soft Drop<br>Space Hard Drop<br>C Hold
        </div>
      </div>
    `;

    const canvas = el.querySelector("canvas");
    const ctx = canvas.getContext("2d");
    const holdCanvas = el.querySelector("#hold-canvas");
    const holdCtx = holdCanvas.getContext("2d");
    const nextCanvas = el.querySelector("#next-canvas");
    const nextCtx = nextCanvas.getContext("2d");

    const scoreEl = el.querySelector("#tetris-score");
    const levelEl = el.querySelector("#tetris-level");
    const linesEl = el.querySelector("#tetris-lines");

    const engine = new TetrisEngine();
    const CELL = 30;
    let running = false;
    let paused = false;
    let raf = null;
    let last = 0;
    let high = Number(Storage.get("webos.tetris.high", 0));

    function drawPiece(context, piece, offsetX, offsetY, cellSize, ghost = false) {
      context.save();
      for (let r = 0; r < piece.shape.length; r++) {
        for (let c = 0; c < piece.shape[r].length; c++) {
          if (piece.shape[r][c]) {
            const x = offsetX + c * cellSize;
            const y = offsetY + r * cellSize;
            if (ghost) {
              context.strokeStyle = piece.color;
              context.lineWidth = 2;
              context.strokeRect(x + 1, y + 1, cellSize - 2, cellSize - 2);
            } else {
              context.fillStyle = piece.color;
              context.fillRect(x, y, cellSize, cellSize);
              context.fillStyle = "rgba(255,255,255,0.2)";
              context.fillRect(x, y, cellSize, cellSize / 2);
              context.strokeStyle = "rgba(0,0,0,0.3)";
              context.strokeRect(x, y, cellSize, cellSize);
            }
          }
        }
      }
      context.restore();
    }

    function draw() {
      // Board background
      ctx.fillStyle = "#0a0a0f";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Grid
      ctx.strokeStyle = "#1a1a2e";
      ctx.lineWidth = 1;
      for (let x = 0; x <= engine.cols; x++) {
        ctx.beginPath();
        ctx.moveTo(x * CELL, 0);
        ctx.lineTo(x * CELL, canvas.height);
        ctx.stroke();
      }
      for (let y = 0; y <= engine.rows; y++) {
        ctx.beginPath();
        ctx.moveTo(0, y * CELL);
        ctx.lineTo(canvas.width, y * CELL);
        ctx.stroke();
      }

      // Locked cells
      for (let r = 0; r < engine.rows; r++) {
        for (let c = 0; c < engine.cols; c++) {
          if (engine.board[r][c]) {
            ctx.fillStyle = engine.board[r][c];
            ctx.fillRect(c * CELL, r * CELL, CELL, CELL);
            ctx.fillStyle = "rgba(255,255,255,0.15)";
            ctx.fillRect(c * CELL, r * CELL, CELL, CELL / 2);
            ctx.strokeStyle = "rgba(0,0,0,0.3)";
            ctx.strokeRect(c * CELL, r * CELL, CELL, CELL);
          }
        }
      }

      // Ghost
      if (!engine.gameOver) {
        const ghost = { ...engine.current, y: engine.getGhostY() };
        drawPiece(ctx, ghost, ghost.x * CELL, ghost.y * CELL, CELL, true);
        // Current
        drawPiece(ctx, engine.current, engine.current.x * CELL, engine.current.y * CELL, CELL);
      }

      // Hold
      holdCtx.clearRect(0, 0, holdCanvas.width, holdCanvas.height);
      if (engine.hold) {
        const def = TETROMINOES[engine.hold];
        const piece = { shape: def.shape, color: def.color };
        const size = 18;
        const offX = (holdCanvas.width - piece.shape[0].length * size) / 2;
        const offY = (holdCanvas.height - piece.shape.length * size) / 2;
        drawPiece(holdCtx, piece, offX, offY, size);
      }

      // Next
      nextCtx.clearRect(0, 0, nextCanvas.width, nextCanvas.height);
      if (engine.queue[0]) {
        const def = TETROMINOES[engine.queue[0]];
        const piece = { shape: def.shape, color: def.color };
        const size = 18;
        const offX = (nextCanvas.width - piece.shape[0].length * size) / 2;
        const offY = (nextCanvas.height - piece.shape.length * size) / 2;
        drawPiece(nextCtx, piece, offX, offY, size);
      }

      // Stats
      scoreEl.textContent = engine.score;
      levelEl.textContent = engine.level;
      linesEl.textContent = engine.lines;

      // Overlays
      if (engine.gameOver) {
        ctx.fillStyle = "rgba(0,0,0,0.7)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#fff";
        ctx.font = "bold 26px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Game Over", canvas.width / 2, canvas.height / 2 - 10);
        ctx.font = "16px system-ui";
        ctx.fillText(`Score: ${engine.score}`, canvas.width / 2, canvas.height / 2 + 20);
      }

      if (paused && !engine.gameOver) {
        ctx.fillStyle = "rgba(0,0,0,0.5)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#fff";
        ctx.font = "bold 24px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Paused", canvas.width / 2, canvas.height / 2);
      }
    }

    function loop(now) {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      const dt = now - last;
      last = now;
      if (!paused && !engine.gameOver) {
        engine.update(dt);
      }
      draw();
    }

    function start() {
      if (engine.gameOver) {
        engine.reset();
      }
      running = true;
      paused = false;
      last = performance.now();
      raf = requestAnimationFrame(loop);
    }

    function pause() {
      paused = !paused;
    }

    el.querySelector("[data-action='start']").onclick = start;
    el.querySelector("[data-action='pause']").onclick = pause;

    el.tabIndex = 0;
    el.addEventListener("keydown", (e) => {
      if (!running || engine.gameOver) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          start();
        }
        return;
      }

      switch (e.key) {
        case "ArrowLeft": e.preventDefault(); engine.move(-1, 0); break;
        case "ArrowRight": e.preventDefault(); engine.move(1, 0); break;
        case "ArrowDown": e.preventDefault(); engine.softDrop(); break;
        case "ArrowUp": e.preventDefault(); engine.rotate(); break;
        case " ": e.preventDefault(); engine.hardDrop(); break;
        case "c": case "C": e.preventDefault(); engine.holdPiece(); break;
        case "p": case "P": e.preventDefault(); pause(); break;
      }
    });

    draw();

    return {
      el,
      onMount() {
        el.focus();
      },
      onUnmount() {
        running = false;
        cancelAnimationFrame(raf);
        if (engine.score > high) {
          Storage.set("webos.tetris.high", engine.score);
        }
      }
    };
  }
};
