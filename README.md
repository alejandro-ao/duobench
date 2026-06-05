# kimi-claude-bench

Model-agnostic benchmark for **planner × implementer** agent pairings, run over Pi RPC.

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

## Run

```bash
# validate the full pipeline with stubbed model calls (no API spend)
uv run kcbench run --dry-run

# one real condition, one trial
uv run kcbench run --conditions gpt-solo --trials 1

# the whole config, 3 trials each (for error bars)
uv run kcbench run --trials 3
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

## Outputs

Each run writes `runs/<timestamp>/`:

```
report.html       visual run report: builds, screenshots, agent threads, timing/tokens/cost
conditions/<id>/trial-<n>/
  plan.md                    planner output (the handoff artifact)
  planner-transcript.json    raw planner thread + timing/token/cost stats
  implementer-transcript.json raw implementer turns + tool/message stats
  judge-transcripts/         one raw judge thread per judge model
  build/                     implementer's files (index.html at root)
  screenshots/               desktop + per-app launch shots
  verify.json                Playwright smoke signals
  trial.json                 record + judge meta/scores
results.json                 aggregated scores
results/                     leaderboard, dimension-radar, cost-vs-quality, self-bias (PNG + CSV)
```

Regenerate a report for an existing run:

```bash
uv run kcbench report runs/<timestamp>
```

Committed chart/CSV artifacts are also mirrored to top-level `results/`.

## Scoring

Judges score three dimensions 1–10 (`architecture`, `correctness`, `visual_ux`), averaged
across the panel. `cost_efficiency` is computed objectively (quality ÷ $) — not judged. A
self-bias matrix shows each judge's score per build to surface a model favoring its own work.

Smoke test "boots OK" = desktop + taskbar render, no fatal console error, and ≥3 apps launch.
