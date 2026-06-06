# duobench

Cost-efficiency benchmark for **planner × implementer** LLM duos, run over Pi RPC.

Each condition spawns a fresh *planner* session to design a WebOS, hands the plan text
(only the plan — not the planner's reasoning) to a fresh *implementer* session that builds
it, then a judge panel scores the result. Cost is captured per phase, including cached-token usage when Pi reports it; charts show the
cost/quality trade-off. Nothing about "challenger vs flagship" is baked in — you measure
whatever combinations you list in config.

See `DESIGN.md` for the full design rationale.

## Install

```bash
uv sync
uv run playwright install chromium
```

Requires the `pi` binary on PATH (`pi --mode rpc`) with the providers you reference in
config already registered.

## Quick start for a cloud agent

If you are handing this repo to an agent or remote runner, tell it to run **one condition
first** and return the generated `report.html`.

```bash
# 1. Install deps
uv sync
uv run playwright install chromium

# 2. Validate local wiring without API/model spend
uv run duobench run --dry-run --conditions gpt-x-kimi --trials 1 --no-live

# 3. Run one real GPT-planner × Kimi-implementer trial
uv run duobench run \
  --conditions gpt-x-kimi \
  --trials 1 \
  --no-live \
  --plan-timeout 600 \
  --impl-timeout 1800 \
  --judge-timeout 300
```

Expected final artifact:

```bash
open runs/<timestamp>/report.html
```

For a copy/paste prompt you can give to a cloud coding agent, see
[`AGENT_RUN_PROMPT.md`](AGENT_RUN_PROMPT.md).

## Run

```bash
# validate the full pipeline with stubbed model calls (no API spend)
uv run duobench run --dry-run

# one real condition, one trial
uv run duobench run --conditions gpt-solo --trials 1

# the whole config, 3 trials each (for error bars)
uv run duobench run --trials 3
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--trials N` | `1` | Trials per condition (variance / error bars) |
| `--conditions a,b,c` | all | Comma-separated condition ids to run |
| `--dry-run` | off | Stub all model calls + canned judge scores |
| `--out DIR` | `runs` | Output root |
| `--models-config` | `config/models.yaml` | Model registry |
| `--conditions-config` | `config/conditions.yaml` | Combinations |
| `--plan-timeout` | `600` | Planner wall-clock (s) |
| `--impl-timeout` | `1800` | Implementer wall-clock (s) |
| `--judge-timeout` | `300` | Per-judge wall-clock (s) |
| `--live` / `--no-live` | auto | Force-enable/disable the Rich live dashboard |

## Running in tmux / long-running environments

Real runs can take a while. For a remote machine, prefer `tmux` and plain logs:

```bash
tmux new-session -d -s duobench \
  'cd /path/to/agent-synergy-eval && \
   PYTHONUNBUFFERED=1 uv run duobench run \
     --conditions gpt-x-kimi \
     --trials 1 \
     --no-live \
     --plan-timeout 600 \
     --impl-timeout 1800 \
     --judge-timeout 300 \
     2>&1 | tee /tmp/duobench.log'
```

Monitor:

```bash
tmux attach -t duobench
# detach safely with Ctrl-b, then d
tail -f /tmp/duobench.log
```

## Configuration

Two flat files, no tiers, fully manual retargeting.

**`config/models.yaml`** — registry + judge panel:

```yaml
models:
  kimi-k2.6:
    provider: kimi-coding        # Pi provider id
    model_id: kimi-for-coding    # Pi model id
    pricing: { input: 0.95, output: 4.00 }   # $/MTok; optional cache_read/cache_write supported
  gpt-5.5:
    provider: openai-codex
    model_id: gpt-5.5
    pricing: { input: 5.00, output: 30.00 }
judges:
  - kimi-k2.6
  - gpt-5.5
```

**`config/conditions.yaml`** — combinations (`planner`/`implementer` are keys into `models`):

```yaml
conditions:
  - { id: kimi-solo,  planner: kimi-k2.6, implementer: kimi-k2.6 }
  - { id: gpt-x-kimi, planner: gpt-5.5,   implementer: kimi-k2.6 }
```

To benchmark a different lineup (e.g. DeepSeek × MiniMax) just rewrite these two files.
Config is validated up front: any planner/implementer/judge that isn't a registered model
key fails fast before any model is called.

## Live CLI

When attached to an interactive terminal, `duobench run` shows a Rich live dashboard with
current phase, spinner, elapsed time, event/message/tool-call counts, the latest tool call,
tokens, cache tokens, configured cost, and Pi-reported cost. Use `--no-live` for plain logs or `--live` to force
it on.

## Outputs

Each run writes `runs/<timestamp>/`:

```
report.html       visual run report: builds, screenshots, agent threads, timing/tokens/cost
conditions/<id>/trial-<n>/
  plan.md                    planner output (the handoff artifact)
  planner-transcript.json    raw planner thread + timing/token/cost stats
  planner-events.jsonl       raw Pi RPC events for debugging/live UI adaptation
  implementer-transcript.json raw implementer turns + tool/message stats
  implementer-events.jsonl   raw Pi RPC events from the implementer session
  judge-transcripts/         one raw judge thread per judge model (+ *.events.jsonl)
  build/                     implementer's files (index.html at root)
  screenshots/               desktop + per-app launch shots
  verify.json                Playwright smoke signals
  trial.json                 record + judge meta/scores
results.json                 aggregated scores
results/                     leaderboard, dimension-radar, cost-vs-quality, self-bias (PNG + CSV)
```

Regenerate a report for an existing run:

```bash
uv run duobench report runs/<timestamp>
```

Committed chart/CSV artifacts are also mirrored to top-level `results/`.

## Scoring

Judges score three dimensions 1–10 (`architecture`, `correctness`, `visual_ux`), averaged
across the panel. `cost_efficiency` is computed objectively (quality ÷ $) — not judged. A
self-bias matrix shows each judge's score per build to surface a model favoring its own work.

Smoke test "boots OK" = desktop + taskbar render, no fatal console error, and ≥3 apps launch.
