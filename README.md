<div align="center">

```
    ██████╗ ██╗   ██╗ ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗██╗  ██╗
    ██╔══██╗██║   ██║██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝██║  ██║
    ██║  ██║██║   ██║██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║     ███████║
    ██║  ██║██║   ██║██║   ██║██╔══██╗██╔══╝  ██║╚██╗██║██║     ██╔══██║
    ██████╔╝╚██████╔╝╚██████╔╝██████╔╝███████╗██║ ╚████║╚██████╗██║  ██║
    ╚═════╝  ╚═════╝  ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝
```

<h3>Benchmark planner × implementer AI coding-agent duos on real GitHub issue → pull request workflows</h3>

<p>
  <a href="https://github.com/alejandro-ao/agent-synergy-eval/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT">
  </a>
  <a href="https://github.com/alejandro-ao/agent-synergy-eval/actions">
    <img src="https://img.shields.io/badge/tests-passing-brightgreen" alt="Tests">
  </a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/pi-integrated-9cf" alt="Pi">
  <a href="https://github.com/alejandro-ao/agent-synergy-eval/stargazers">
    <img src="https://img.shields.io/github/stars/alejandro-ao/agent-synergy-eval?style=social" alt="GitHub Stars">
  </a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> •
  <a href="#installation">Install</a> •
  <a href="#usage">Usage</a> •
  <a href="#output">Output</a> •
  <a href="#design">Design</a>
</p>

</div>

---

## Overview

**duobench** runs every planner/implementer pairing you choose through [Pi](https://pi.dev) RPC to measure which model duos produce the best **quality-per-dollar** for realistic software engineering work.

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐     ┌──────────┐
│   GitHub    │────▶│     Planner     │────▶│ Implementer │────▶│    PR    │
│    Issue    │     │  (plan + handoff)│     │  (code + push)│     │          │
└─────────────┘     └─────────────────┘     └─────────────┘     └────┬─────┘
                                                                     │
                              ┌──────────────────────────────────────┘
                              ▼
                       ┌─────────────┐
                       │    Judge    │  ◄── scores on 4 dimensions + cost
                       │  (evaluate) │
                       └─────────────┘
```

### What It Does

1. **Planner** inspects a GitHub issue and the local repo, then writes a handoff plan.
2. **Implementer** receives the issue + plan in an isolated git worktree, fixes the issue, commits, pushes, and opens a PR.
3. **Judge** models inspect the issue and PR with `git`/`gh` and score the result.
4. **Harness** writes transcripts, costs, charts, CSVs, and an HTML report.

> ⚠️ **Real runs create branches and pull requests.** Use a repo where that is expected, and consider starting with one condition and one trial.

---

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- `git`
- GitHub CLI: [`gh`](https://cli.github.com/) (authenticated)
- `pi` on PATH, with configured model providers

Check basics:

```bash
gh auth status
pi --version
git status
```

---

## Installation

**From this checkout:**

```bash
uv sync
uv run playwright install chromium
```

**As a uv tool from PyPI:**

```bash
uv tool install duobench
uvx playwright install chromium
```

**Or directly from GitHub:**

```bash
uv tool install git+https://github.com/alejandro-ao/agent-synergy-eval.git
uvx playwright install chromium
```

---

## Quick Start

### 1. Validate without spending tokens

```bash
uv run duobench --dry-run --models kimi-k2.6,gpt-5.5 --trials 1 --no-live
```

Open the generated report:

```bash
open runs/<timestamp>/report.html
```

### 2. Run one real condition first

```bash
uv run duobench \
  --issue https://github.com/org/repo/issues/123 \
  --conditions gpt-x-kimi \
  --trials 1 \
  --no-live
```

### 3. Run a full model matrix

```bash
uv run duobench \
  --issue https://github.com/org/repo/issues/123 \
  --models openai-codex/gpt-5.5:high,kimi-coding/kimi-for-coding:high,anthropic/claude-opus-4.8 \
  --trials 1
```

With three models and one trial, this runs **3 planner sessions**, **9 implementer sessions**, and a **judge panel over every PR**.

---

## Usage

### Common Commands

```bash
# Full planner × implementer matrix from Pi model specs
uv run duobench --issue https://github.com/org/repo/issues/123 --models openai-codex/gpt-5.5:high,kimi-coding/kimi-for-coding:high --trials 1

# Rectangular matrix: selected planners crossed with selected implementers
uv run duobench --issue https://github.com/org/repo/issues/123 \
  --planners openai-codex/gpt-5.5:high,kimi-coding/kimi-for-coding:high \
  --implementers kimi-coding/kimi-for-coding:high --trials 1

# Explicit conditions from config/conditions.yaml
uv run duobench --issue https://github.com/org/repo/issues/123 --conditions gpt-x-kimi --trials 1

# Serial execution (useful to avoid PR/branch chaos while testing)
uv run duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6,gpt-5.5 --parallel 1 --trials 1

# Regenerate an HTML report from an existing run
uv run duobench report runs/<timestamp>
```

`duobench ...` is shorthand for `duobench run ...`.

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--issue URL` | required for real runs | GitHub issue URL/reference. Agents fetch it themselves with `gh`. |
| `--models a,b,c` | off | Generate full planner × implementer matrix from Pi model specs. |
| `--planners a,b` | off | Planner Pi model specs for rectangular matrix. Use with `--implementers`. |
| `--implementers a,b` | off | Implementer Pi model specs for rectangular matrix. Use with `--planners`. |
| `--judges a,b` | `--models` or config judges | Judge Pi model specs. |
| `--conditions a,b` | all config conditions | Run named condition IDs from `conditions.yaml`. |
| `--trials N` | `1` | Trials per condition. |
| `--parallel auto\|all\|N` | `auto` | Planner/implementation concurrency. Use `1` for serial. |
| `--dry-run` | off | Stub model calls and generate synthetic outputs. |
| `--out DIR` | `runs` | Output directory root. |
| `--models-config PATH` | `config/models.yaml` | Optional legacy model registry / default judges. |
| `--conditions-config PATH` | `config/conditions.yaml` | Condition preset path. |
| `--costs-config PATH` | `costs.yaml` | Optional fallback pricing when Pi does not report cost. |
| `--plan-timeout SEC` | `600` | Planner wall-clock timeout. |
| `--impl-timeout SEC` | `1800` | Implementer wall-clock timeout. |
| `--judge-timeout SEC` | `300` | Per-judge timeout. |
| `--pi-sessions` / `--no-pi-sessions` | on | Save Pi sessions in Pi's normal session store. |
| `--live` / `--no-live` | auto (TTY) | Rich live dashboard. |
| `--skip-model-check` | off | Skip the fail-fast Pi model/auth validation pass. |
| `--debug` | off | Show full Python tracebacks on errors. |
| `--live` / `--no-live` | auto | Rich live dashboard. |
| `--skip-model-check` | off | Skip fail-fast Pi model/auth validation. |

---

## Models & Costs

### Model Specs

`--models`, `--planners`, `--implementers`, `--judges`, and the `planner`/`implementer` fields in `conditions.yaml` all accept the same model spec format. There are two equivalent ways to write a spec:

- **Registry key** (a short alias defined in `config/models.yaml`): `kimi-k2.6`, `gpt-5.5`
- **Pi spec** (what you would pass to `pi --model`): `kimi-coding/kimi-for-coding`, `openai-codex/gpt-5.5`

You can append a `:thinking` suffix to either form to set the thinking level for that run:

```bash
--models kimi-k2.6:high,openai-codex/gpt-5.5:high
```

Valid levels are `off`, `minimal`, `low`, `medium`, `high`, `xhigh`. A registry key with a `:thinking` suffix overrides the registry's `thinking` field for that run. Unknown keys are marked with `*` in dry-run output — they're passed straight to Pi but skip the registry's defaults for `provider`, `thinking`, and `pricing`.

Before a real benchmark starts, duobench validates each unique model by launching Pi with that model and asking it to reply `OK`. Use `--skip-model-check` only if you intentionally want to bypass that fail-fast auth/model check.

### Cost Accounting

Duobench prefers Pi/provider-reported cost when available. If Pi does not report cost, duobench falls back to the model's `pricing` block in `config/models.yaml` or, failing that, rates from `costs.yaml`. Rates are dollars per million tokens:

```yaml
# config/models.yaml — pricing for a registry key
models:
  kimi-k2.6:
    provider: kimi-coding
    model_id: kimi-for-coding
    pricing: { input: 0.95, output: 4.00 }
```

```yaml
# costs.yaml — pricing for a direct Pi spec, keyed by the exact spec string
models:
  kimi-coding/kimi-for-coding:
    input: 0.95
    output: 4.00
  kimi-coding/kimi-for-coding:high:
    input: 0.95
    output: 4.00
    cache_read: 0.15
    cache_write: 0.95
```

If neither Pi nor any of the above provides cost information, duobench records cost as `0` with source `unknown`. The dry-run leaderboard prints a warning when any condition has source `unknown`, because `cost_efficiency` is meaningless without pricing.

### Optional Config Files

`config/conditions.yaml` is useful for named manual pairings:

```yaml
conditions:
  - id: gpt-x-kimi
    planner: openai-codex/gpt-5.5:high
    implementer: kimi-coding/kimi-for-coding:high
```

`config/models.yaml` remains supported mainly for packaged defaults, legacy condition aliases, and default judges. For most new experiments, prefer direct Pi model specs in the CLI plus optional `costs.yaml`.

---

## What Agents Are Asked To Do

### Planner

- Inspect the issue using `gh`
- Inspect the local repository
- Produce a concise implementation plan
- **Avoid** modifying files, branches, commits, pushes, or PRs

### Implementer

- Inspect the issue with `gh`
- Create a branch in an isolated worktree
- Make code changes and run appropriate checks
- Commit, push, and open a PR
- Return only the PR id or PR URL

### Judge

Each judge receives the issue URL, PR id, planner handoff, and harness metadata. It can inspect the PR with `git` and `gh`, but must not mutate anything.

| Dimension | Meaning |
|-----------|---------|
| `task_completion` | Does the PR address the issue and avoid unrelated work? |
| `correctness` | Is the behavior likely correct and robust? |
| `code_quality` | Are changes maintainable, idiomatic, and appropriately scoped? |
| `verification` | Were meaningful tests/checks included or run? |

`cost_efficiency` is computed by the harness as quality divided by cost.

---

## Output

Each run writes to `runs/<timestamp>/`:

```text
report.html
results.json
results/
  leaderboard.png / leaderboard.csv
  dimension-radar.png / dimensions.csv
  cost-vs-quality.png / cost-vs-quality.csv
  self-bias-matrix.png / self-bias.csv
shared-plans/<planner>/trial-<n>/
  plan.md
  shared-plan.json
  planner-transcript.json
  planner-events.jsonl
conditions/<condition-id>/trial-<n>/
  plan.md
  worktree/
  verify.json
  trial.json
  implementer-transcript.json
  implementer-events.jsonl
  judge-transcripts/
```

The final CLI output prints a file URL for `report.html`.

---

## Pi Sessions

Real runs save Pi sessions by default, so you can inspect planner, implementer, and judge conversations in Pi's normal session browser/store.

Disable this with:

```bash
uv run duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6 --no-pi-sessions
```

Dry runs never create Pi sessions.

---

## Running Long Benchmarks

Use `tmux` and `--no-live` for remote machines:

```bash
tmux new-session -d -s duobench \
  'cd /path/to/repo && \
   PYTHONUNBUFFERED=1 uv run duobench \
     --issue https://github.com/org/repo/issues/123 \
     --models kimi-k2.6,gpt-5.5 \
     --trials 1 \
     --parallel 1 \
     --no-live \
     2>&1 | tee /tmp/duobench.log'
```

Monitor:

```bash
tmux attach -t duobench
tail -f /tmp/duobench.log
```

---

## Safety Tips

- ✅ Start with `--dry-run`.
- ✅ Start real runs with `--conditions one-condition --trials 1`.
- ✅ Use `--parallel 1` until you are comfortable with branch/PR behavior.
- ✅ Run against a test repository or issue first.
- ⚠️ Expect one PR per implementer attempt.
- ⚠️ Judges are instructed not to mutate PRs, but implementers intentionally do.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `--issue is required` | Real runs require a GitHub issue: `uv run duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6` |
| `gh CLI is required` | Install and authenticate: `gh auth login && gh auth status` |
| Pi cannot find a model | Check `config/models.yaml`. `provider` and `model_id` must match what your Pi installation knows. |
| Too many branches/PRs | Use fewer models, fewer trials, explicit `--conditions`, and `--parallel 1`. |

---

## Design

- [`DESIGN.md`](DESIGN.md) — design rationale
- [`.exploration/`](.exploration/) — architecture walkthrough generated for this codebase

---

<div align="center">

**Made with ❤️ by [Alejandro AO](https://github.com/alejandro-ao)**

<a href="https://github.com/alejandro-ao/agent-synergy-eval/stargazers">⭐ Star this repo</a> if you find it useful!

</div>
