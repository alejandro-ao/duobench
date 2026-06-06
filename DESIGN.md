# duobench — Design

A reproducible, **model-agnostic** benchmark that measures the quality and cost of
**planner → implementer** agent pairings, to find the best cost/quality trade-off for
AI-assisted coding.

The tool is neutral: it measures whatever planner×implementer **combinations** you define
in config, over any models Pi can run. The *narrative* (e.g. "cheap model plans, expensive
model builds") comes from which combinations you choose — it is **not** baked into the tool.

Companion experiment for the video **"Kimi + Claude Code: The Best AI Coding Duo for Cheap"**
(`videos/workflow/projects/2026-06-kimi-claude-code/`).

---

## 1. Thesis (for THIS video — not hard-coded in the tool)

A cheap, long-context model (Kimi K2.6) can do the *planning/architecture* while a strong
agent does the *implementation* — yielding near-top quality at a fraction of the cost of
running an expensive model for both roles.

This repo turns that claim into **numbers and charts**. But the same harness can later test
entirely different lineups (DeepSeek × MiniMax, etc.) by editing config alone — no code
changes. Today's flagship models (Opus 4.8, GPT-5.5) will be superseded; swapping them in
is a config edit.

---

## 2. Experimental design

### Variables

- **Models:** any set defined in `config/models.yaml` (a flat registry). For this video:
  Kimi K2.6, GPT-5.5, Claude Opus 4.8. No "tiers" — every model is just an entry.
- **Roles (2):** Planner (architect) + Implementer (coder).
- **Conditions:** concrete planner×implementer pairs. The simplest CLI path is
  `--models a,b,c`, which expands to the full matrix (N planner samples, N² builds per
  trial). `config/conditions.yaml` is still supported for hand-picked/manual pairings.
  There are no challenger/flagship semantics baked into the tool.
- **Benchmark task (1):** Build a WebOS from scratch (vanilla JS/HTML/CSS) — one rich,
  visual artifact. Prompt is the existing WebOS prompt from the video `plan.md`.

### Conditions for this video (7, defined in config)

| # | Planner   | Implementer | Type   |
|---|-----------|-------------|--------|
| 1 | Kimi      | Kimi        | solo   |
| 2 | GPT-5.5   | GPT-5.5     | solo   |
| 3 | Opus 4.8  | Opus 4.8    | solo   |
| 4 | Kimi      | GPT-5.5     | hybrid |
| 5 | GPT-5.5   | Kimi        | hybrid |
| 6 | Kimi      | Opus 4.8    | hybrid |
| 7 | Opus 4.8  | Kimi        | hybrid |

These can be produced directly with `--models kimi-k2.6,gpt-5.5,claude-opus-4.8`, or by
listing equivalent rows in `conditions.yaml`. To test a different lineup later, add the
model entries and pass a new `--models` list — nothing in `src/` changes.

### Trials

- `--trials N` flag. Default `1` (cheap, no error bars).
- `--trials 3` runs each condition 3× → plottable variance / error bars.

---

## 3. Configuration schema (the flexibility layer)

The entire "which models, which judges" question lives in `models.yaml`. Pair selection is
normally generated from CLI flags, while `conditions.yaml` provides optional named presets.
`src/` is generic and never names a model.

### `config/models.yaml` — flat registry + judges

```yaml
# Every model is just an entry. Add DeepSeek/MiniMax/etc. here; nothing in src/ changes.
# provider/model_id are passed straight to Pi RPC set_model.
models:
  kimi-k2.6:
    provider: kimi
    model_id: kimi-k2.6
    pricing: { input: 0.95, output: 4.00 }     # $/MTok
  gpt-5.5:
    provider: openai
    model_id: gpt-5.5
    pricing: { input: 5.00, output: 30.00 }
  claude-opus-4.8:
    provider: anthropic
    model_id: claude-opus-4-8
    pricing: { input: 5.00, output: 25.00 }

# Judge panel — explicit, chosen independently of competitors.
judges:
  - kimi-k2.6
  - gpt-5.5
  - claude-opus-4.8
```

### `config/conditions.yaml` — optional explicit combinations

```yaml
# Optional named presets. planner/implementer are keys into models.yaml.
# For full cross-product benchmarking, prefer: duobench run --models kimi-k2.6,gpt-5.5,...
conditions:
  - { id: kimi-solo,   planner: kimi-k2.6,       implementer: kimi-k2.6 }
  - { id: gpt-solo,    planner: gpt-5.5,         implementer: gpt-5.5 }
  - { id: opus-solo,   planner: claude-opus-4.8, implementer: claude-opus-4.8 }
  - { id: kimi-x-gpt,  planner: kimi-k2.6,       implementer: gpt-5.5 }
  - { id: gpt-x-kimi,  planner: gpt-5.5,         implementer: kimi-k2.6 }
  - { id: kimi-x-opus, planner: kimi-k2.6,       implementer: claude-opus-4.8 }
  - { id: opus-x-kimi, planner: claude-opus-4.8, implementer: kimi-k2.6 }
```

### Reusability

- **Swap a model** (Opus 4.8 → Opus 5): add/edit its entry in `models.yaml`, then use the
  new key in `--models` or optional `conditions.yaml` presets. Fully manual, no aliases.
- **Test a different lineup** (DeepSeek × MiniMax): add the models, run `--models deepseek,minimax`.
- **Validation:** at load, the harness asserts every `planner`/`implementer`/`judges` key
  exists in `models` and fails fast with a clear error otherwise.

---

## 4. Execution model

### The harness is a SCRIPT, not an agent

`run.py` is a deterministic Python orchestrator triggered from the CLI. It does **no
reasoning** — it sequences phases, spawns Pi sessions, captures tokens, runs browser
checks, computes averages, draws charts. The only agentic work happens *inside* the Pi
sessions being measured (planner, implementer, judges).

```
you → `uv run duobench run --models kimi,gpt,opus --trials 3`
        └─ stage 1: for each unique planner × trial:
             plan_phase  → spawn Pi RPC (planner model)    → shared plan.md + cost
        └─ stage 2: for each planner×implementer condition × trial:
             impl_phase  → spawn FRESH Pi RPC (impl model) → build/ + cost
             verify      → Playwright headless             → smoke results + screenshots
        └─ stage 3: judge_phase scores every build → averages/charts/report

Planner and build stages use one simple concurrency knob: `--parallel auto|all|N`.
```

### Single uniform substrate: Pi RPC

Every model runs through **Pi RPC** (`pi --mode rpc`), a JSONL subprocess protocol over
stdin/stdout. Switching models is just a `set_model` command (provider + model_id come
straight from `models.yaml`):

```json
{"type": "set_model", "provider": "anthropic", "modelId": "claude-opus-4-8"}
{"type": "prompt", "message": "..."}
```

Pi natively supports `anthropic`, `openai`, and `kimi`/Moonshot providers. This means
there is **no special-casing per model** — the harness treats all three identically.

- **Kimi:** already configured in the user's Pi setup (Kimi API). No extra work.
- **GPT-5.5:** `openai` provider via OpenAI API key in Pi.
- **Opus 4.8:** `anthropic` provider — user adds the Claude API key to Pi.

### Session isolation = the handoff

The planner and implementer run as **separate Pi sessions**. The implementer never sees
the planner's reasoning thread — only the produced `plan.md`. This mirrors the real Pi
production flow (plan → GitHub issue → fresh implementer reads it). Here the handoff
artifact is just a file on disk.

### No turn cap (by design)

Implementer sessions run to completion with **no hard turn cap**. Realistic agent behavior
— including a model that loops through many tool calls — is part of what we measure: it
naturally inflates that condition's cost and hurts its cost-efficiency score. The only
guardrail is a generous **wall-clock safety timeout** to prevent a hung session from
blocking the whole suite. A session that hits the ceiling is recorded as a
`timeout`/`failure` data point (not silently dropped).

The implementer phase supports a bounded **multi-turn loop** (`follow_up` "continue
building") so a large WebOS can be completed across turns — turns are counted and cost
is accumulated, so verbose builders still pay for it in the metrics.

---

## 5. Scoring

### Rubric (4 dimensions, each scored 1–10)

| Dimension            | What it measures                                          | Primary inputs                          |
|----------------------|-----------------------------------------------------------|-----------------------------------------|
| Architecture quality | Modularity, separation of concerns, extensibility         | source code, plan.md                    |
| Code correctness     | Does it run, bugs, feature completeness                   | source code, **smoke-test results**     |
| Visual/UX design     | Polish, aesthetics, animations                            | **screenshots**, source (CSS)           |
| Cost efficiency      | Quality per dollar — computed, NOT model-judged           | token/cost data (objective)             |

- **Architecture, Correctness, Visual/UX** → scored by a 3-model judge panel.
- **Cost efficiency** → computed objectively by the harness (quality ÷ $), not judged.
- **Screenshots feed the Visual/UX dimension specifically** (and CSS review).

### Judge panel (explicit, configurable), averaged

The judge panel is an **explicit list** in `config/models.yaml` (`judges:`), chosen
independently of who competes — so you can add a neutral judge or drop a competitor from
judging. For this video the panel is Kimi K2.6, GPT-5.5, Opus 4.8.

Each judge scores **every** build on the 3 judged dimensions, output as strict JSON.
Scores are averaged across all judges per build per dimension. Judges run at
**temperature 0** where the provider supports it.

Judge input bundle per build: **source code + screenshots + smoke-test results**.

### Self-bias is surfaced, not hidden

With a judge × build matrix we can show "does a judge rate its own model's builds higher
than the other judges do?" Averaging across the panel cancels most bias; the matrix is
plotted so the video can be honest about it.

---

## 6. Cost capture

Pi RPC `agent_end` events carry the full message history with token usage. Per phase we
sum input/output tokens and multiply by per-MTok rates from each model's entry in
`config/models.yaml`. Rates live with the model definition, so adding a new model brings
its own pricing. Example (this video's lineup):

| Model       | Provider  | Input $/MTok | Output $/MTok | Context |
|-------------|-----------|--------------|---------------|---------|
| Kimi K2.6   | kimi      | 0.95         | 4.00          | 256K    |
| GPT-5.5     | openai    | 5.00         | 30.00         | ~1M     |
| Opus 4.8    | anthropic | 5.00         | 25.00         | 1M      |

Cost is captured **per phase** (plan vs implement) so the charts can break down where the
money goes. `models.yaml` is the single source of truth for rates.

---

## 7. Verification (Playwright headless)

After each build, the harness loads it headless and records objective signals:

- Boots without fatal console errors
- Desktop/taskbar renders
- Windows open; at least N apps launch
- Per-app launch pass/fail
- Captures screenshots (desktop + each opened app) for the Visual/UX judge input

These feed **Code correctness** (objective pass/fail) and **Visual/UX** (screenshots).

---

## 8. Outputs / charts

`results/` (committed, for the video):

- `leaderboard.png` — overall averaged score per condition (bar)
- `dimension-radar.png` — per-condition profile across the 4 dimensions
- `cost-vs-quality.png` — **the money chart**: X = $ spent, Y = avg quality, point per
  condition. The trade-off winner is whichever condition sits high + far-left.
- `self-bias-matrix.png` — judge × build heatmap
- `results.json` — full numeric results (also the data source for all charts)

Every chart also writes its underlying numbers as CSV (`leaderboard.csv`,
`dimensions.csv`, `cost-vs-quality.csv`, `self-bias.csv`) for re-plotting in your own
video tooling.

With `--trials 3`, charts show mean + error bars.

---

## 9. Proposed repo structure

```
duobench/
├── DESIGN.md                      # this file
├── README.md                      # how to run
├── pyproject.toml                 # uv-managed
├── config/
│   ├── models.yaml                # flat model registry + explicit judges list
│   └── conditions.yaml            # explicit planner×implementer combinations
├── prompts/
│   ├── architect.md               # WebOS planning prompt (from video plan.md)
│   ├── implement.md               # build-from-plan prompt
│   └── judge.md                   # rubric + strict-JSON scoring instructions
├── src/duobench/
│   ├── pi_rpc.py                  # JSONL subprocess driver (spawn/set_model/prompt/collect)
│   ├── plan_phase.py              # planner session → plan.md + cost
│   ├── impl_phase.py              # fresh session → build/ + cost (multi-turn, timeout)
│   ├── verify.py                  # Playwright smoke tests + screenshots
│   ├── judge.py                   # configurable panel scoring + averaging + self-bias
│   ├── cost.py                    # token → $ from models.yaml
│   ├── charts.py                  # matplotlib chart generation + CSV export
│   └── run.py                     # orchestrator CLI (--trials, --conditions, ...)
├── runs/                          # GITIGNORED — generated artifacts
│   └── <timestamp>/
│       ├── conditions/
│       │   └── <planner>__<impl>/[trial-n/]
│       │       ├── plan.md
│       │       ├── build/         # the generated WebOS
│       │       ├── screenshots/
│       │       └── tokens.json    # per-phase token + cost
│       ├── judgments/             # raw per-judge JSON scores
│       └── results.json
└── results/                       # COMMITTED — final charts + results.json for the video
```

`runs/` (raw builds, screenshots, browser binaries) is gitignored; only curated `results/`
artifacts are committed.

---

## 10. Build order (after plan approval)

1. `pyproject.toml` + `uv` env + Playwright install
2. `config/models.yaml` (registry + judges) + `config/conditions.yaml` (combinations) +
   loader with fail-fast validation that all referenced keys exist
3. `prompts/` — port architect/implement prompts from video plan.md; write judge rubric
4. `pi_rpc.py` — the JSONL driver (most critical; everything depends on it)
5. `plan_phase.py` + `impl_phase.py`
6. `verify.py` (Playwright)
7. `judge.py` + `cost.py`
8. `charts.py` (+ CSV export)
9. `run.py` orchestrator (`--trials`, `--conditions`, `--dry-run`) + `README.md`
10. `--dry-run` the full pipeline (stubbed calls), then smoke-test ONE real condition
    before running the whole config

---

## 11. Resolved decisions

1. **WebOS output** — allow a **multi-file project tree** under `build/`. Verify + judge
   read the whole tree; entry point is `build/index.html`.
2. **Judge temperature** — **pinned to 0** wherever the provider supports it (deterministic
   scoring). Recorded per-judge in case a provider ignores it.
3. **Smoke-test "boots OK" threshold** — chosen by us: a build counts as booting if it
   **renders the desktop + taskbar with no fatal console error AND at least 3 of the
   built-in apps launch successfully**. Per-app launch results are still recorded
   individually so partial builds score proportionally on Code correctness.
4. **Charts** — **matplotlib** (static PNG for the video) + every chart also writes its
   underlying data to CSV (see #6).
5. **`--dry-run` mode** — yes. Stubs all model calls (canned plan/build/scores) and skips
   real Pi spawns so the full pipeline wiring can be tested cheaply end-to-end.
6. **CSV export** — yes. Alongside each chart in `results/`, write the raw numbers as CSV
   (`leaderboard.csv`, `dimensions.csv`, `cost-vs-quality.csv`, `self-bias.csv`) for
   re-plotting in your own video tooling.
