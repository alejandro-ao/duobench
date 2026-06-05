// ============================================
// Vanilla WebOS — Snake Game
// ============================================

const SnakeApp = {
  id: "snake",
  name: "Snake",
  icon: "🐍",
  category: "Games",
  defaultWidth: 520,
  defaultHeight: 580,
  minWidth: 360,
  minHeight: 400,

  create({ os }) {
    const el = document.createElement("div");
    el.className = "app game snake-app";
    el.innerHTML = `
      <div class="game-toolbar">
        <button data-action="start">Start</button>
        <button data-action="pause">Pause</button>
        <div class="game-stats">Score: <span id="snake-score">0</span> | High: <span id="snake-high">0</span></div>
      </div>
      <canvas width="480" height="480"></canvas>
    `;

    const canvas = el.querySelector("canvas");
    const ctx = canvas.getContext("2d");
    const scoreEl = el.querySelector("#snake-score");
    const highEl = el.querySelector("#snake-high");

    const CELL = 24;
    const COLS = 20;
    const ROWS = 20;

    let state = createState();
    let running = false;
    let paused = false;
    let raf = null;
    let last = 0;
    let step = 140;
    let high = Number(Storage.get("webos.snake.high", 0));
    highEl.textContent = high;

    function createState() {
      return {
        snake: [{ x: 8, y: 10 }, { x: 7, y: 10 }, { x: 6, y: 10 }],
        dir: { x: 1, y: 0 },
        nextDir: { x: 1, y: 0 },
        food: randomFood([{ x: 8, y: 10 }, { x: 7, y: 10 }, { x: 6, y: 10 }]),
        score: 0,
        gameOver: false
      };
    }

    function randomFood(snake) {
      let pos;
      do {
        pos = { x: Math.floor(Math.random() * COLS), y: Math.floor(Math.random() * ROWS) };
      } while (snake.some(s => s.x === pos.x && s.y === pos.y));
      return pos;
    }

    function update() {
      if (paused || state.gameOver) return;

      state.dir = { ...state.nextDir };
      const head = { x: state.snake[0].x + state.dir.x, y: state.snake[0].y + state.dir.y };

      // Wall collision
      if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS) {
        gameOver();
        return;
      }

      // Self collision
      if (state.snake.some(s => s.x === head.x && s.y === head.y)) {
        gameOver();
        return;
      }

      state.snake.unshift(head);

      if (head.x === state.food.x && head.y === state.food.y) {
        state.score += 10;
        scoreEl.textContent = state.score;
        step = Math.max(60, 140 - Math.floor(state.score / 50) * 10);
        state.food = randomFood(state.snake);
      } else {
        state.snake.pop();
      }
    }

    function gameOver() {
      state.gameOver = true;
      running = false;
      if (state.score > high) {
        high = state.score;
        Storage.set("webos.snake.high", high);
        highEl.textContent = high;
      }
      os.notifications.push({ title: "Snake", body: `Game Over! Score: ${state.score}` });
    }

    function draw() {
      // Background
      ctx.fillStyle = "#0a0a0f";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Grid
      ctx.strokeStyle = "#1a1a2e";
      ctx.lineWidth = 1;
      for (let x = 0; x <= COLS; x++) {
        ctx.beginPath();
        ctx.moveTo(x * CELL, 0);
        ctx.lineTo(x * CELL, canvas.height);
        ctx.stroke();
      }
      for (let y = 0; y <= ROWS; y++) {
        ctx.beginPath();
        ctx.moveTo(0, y * CELL);
        ctx.lineTo(canvas.width, y * CELL);
        ctx.stroke();
      }

      // Food
      ctx.fillStyle = "#ef4444";
      ctx.beginPath();
      ctx.arc(state.food.x * CELL + CELL / 2, state.food.y * CELL + CELL / 2, CELL / 2 - 2, 0, Math.PI * 2);
      ctx.fill();

      // Snake
      state.snake.forEach((seg, i) => {
        ctx.fillStyle = i === 0 ? "#22c55e" : "#16a34a";
        ctx.fillRect(seg.x * CELL + 1, seg.y * CELL + 1, CELL - 2, CELL - 2);
      });

      // Game over text
      if (state.gameOver) {
        ctx.fillStyle = "rgba(0,0,0,0.6)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#fff";
        ctx.font = "bold 28px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Game Over", canvas.width / 2, canvas.height / 2 - 10);
        ctx.font = "16px system-ui";
        ctx.fillText(`Score: ${state.score}`, canvas.width / 2, canvas.height / 2 + 20);
      }

      // Paused text
      if (paused && !state.gameOver) {
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

      if (now - last >= step) {
        update();
        last = now;
      }
      draw();
    }

    function start() {
      if (state.gameOver) {
        state = createState();
        step = 140;
        scoreEl.textContent = 0;
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

    // Keyboard
    const keyMap = {
      ArrowUp: { x: 0, y: -1 },
      ArrowDown: { x: 0, y: 1 },
      ArrowLeft: { x: -1, y: 0 },
      ArrowRight: { x: 1, y: 0 }
    };

    el.tabIndex = 0;
    el.addEventListener("keydown", (e) => {
      if (keyMap[e.key]) {
        e.preventDefault();
        const nd = keyMap[e.key];
        // Prevent reversing directly
        if (nd.x !== -state.dir.x || nd.y !== -state.dir.y) {
          state.nextDir = nd;
        }
      } else if (e.key === " ") {
        e.preventDefault();
        if (!running || state.gameOver) start();
        else pause();
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
      }
    };
  }
};
