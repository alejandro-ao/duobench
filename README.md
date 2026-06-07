# duobench

Benchmark **planner × implementer** AI coding-agent duos on real GitHub issue → pull request workflows.

`duobench` runs every planner/implementer pairing you choose through [Pi](https://pi.dev) RPC:

1. A planner model inspects a GitHub issue and the local repo, then writes a handoff plan.
2. An implementer model receives the issue + plan in an isolated git worktree.
3. The implementer fixes the issue, commits, pushes, opens a PR, and returns only the PR id.
4. Judge models inspect the issue and PR with `git`/`gh` and score the result.
5. The harness writes transcripts, costs, charts, CSVs, and an HTML report.

The goal is to measure which model pairings produce the best quality-per-dollar for realistic software engineering work.

> **Important:** real runs create branches and pull requests. Use a repo where that is expected, and consider starting with one condition and one trial.

---

## Requirements

For real runs you need:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- `git`
- GitHub CLI: [`gh`](https://cli.github.com/)
- authenticated `gh` with permission to read issues and create PRs
- `pi` on PATH, with the model providers in your config available
- a clean-ish local checkout of the GitHub repo you want to benchmark

Check basics:

```bash
gh auth status
pi --version
git status
```

---

## Install

From this checkout:

```bash
uv sync
uv run playwright install chromium
```

As a uv tool from PyPI:

```bash
uv tool install duobench
uvx playwright install chromium
```

Or directly from GitHub:

```bash
uv tool install git+https://github.com/alejandro-ao/agent-synergy-eval.git
uvx playwright install chromium
```

`playwright` is still used by dry-run/demo artifacts and legacy report checks.

---

## Quick Start

### 1. Validate without spending model/API tokens

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
  --models kimi-k2.6,gpt-5.5,claude-opus-4.8 \
  --trials 1
```

With three models and one trial, this runs:

- 3 planner sessions
- 9 implementer sessions / PR attempts
- judge panel over every PR

---

## Common Commands

```bash
# Full planner × implementer matrix from model keys
uv run duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6,gpt-5.5 --trials 1

# Rectangular matrix: selected planners crossed with selected implementers
uv run duobench --issue https://github.com/org/repo/issues/123 --planners kimi-k2.6,gpt-5.5 --implementers kimi-k2.6 --trials 1

# Explicit conditions from config/conditions.yaml
uv run duobench --issue https://github.com/org/repo/issues/123 --conditions gpt-x-kimi --trials 1

# Serial execution, useful to avoid PR/branch chaos while testing
uv run duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6,gpt-5.5 --parallel 1 --trials 1

# Regenerate an HTML report from an existing run
uv run duobench report runs/<timestamp>
```

`duobench ...` is shorthand for `duobench run ...`.

---

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--issue URL` | required for real runs | GitHub issue URL/reference. Agents fetch it themselves with `gh`. |
| `--models a,b,c` | off | Generate full planner × implementer matrix. |
| `--planners a,b` | off | Planner model keys for rectangular matrix. Use with `--implementers`. |
| `--implementers a,b` | off | Implementer model keys for rectangular matrix. Use with `--planners`. |
| `--conditions a,b` | all config conditions | Run named condition IDs from `conditions.yaml`. |
| `--trials N` | `1` | Trials per condition. |
| `--parallel auto\|all\|N` | `auto` | Planner/implementation concurrency. Use `1` for serial. |
| `--dry-run` | off | Stub model calls and generate synthetic outputs. |
| `--out DIR` | `runs` | Output directory root. |
| `--models-config PATH` | `config/models.yaml` | Model registry path. |
| `--conditions-config PATH` | `config/conditions.yaml` | Condition preset path. |
| `--plan-timeout SEC` | `600` | Planner wall-clock timeout. |
| `--impl-timeout SEC` | `1800` | Implementer wall-clock timeout. |
| `--judge-timeout SEC` | `300` | Per-judge timeout. |
| `--pi-sessions` / `--no-pi-sessions` | on | Save Pi sessions in Pi's normal session store. |
| `--live` / `--no-live` | auto | Rich live dashboard. |

---

## Configuration

Duobench uses two YAML files.

### `config/models.yaml`

Model registry plus judge panel:

```yaml
models:
  kimi-k2.6:
    provider: kimi-coding
    model_id: kimi-for-coding
    thinking: high
    pricing:
      input: 0.95
      output: 4.00

  gpt-5.5:
    provider: openai-codex
    model_id: gpt-5.5
    thinking: off
    pricing:
      input: 5.00
      output: 30.00

judges:
  - kimi-k2.6
  - gpt-5.5
```

Notes:

- `provider` and `model_id` are passed directly to Pi RPC `set_model`.
- `thinking` is optional: `off|minimal|low|medium|high|xhigh`.
- `pricing` is dollars per million tokens.
- Optional `cache_read` and `cache_write` rates are supported.

### `config/conditions.yaml`

Named manual pairings:

```yaml
conditions:
  - id: kimi-solo
    planner: kimi-k2.6
    implementer: kimi-k2.6

  - id: gpt-x-kimi
    planner: gpt-5.5
    implementer: kimi-k2.6
```

For most experiments, use `--models` instead of manually listing every pair.

---

## What Agents Are Asked To Do

### Planner

The planner receives the GitHub issue URL and is told to:

- inspect the issue using `gh`
- inspect the local repository
- produce a concise implementation plan
- avoid modifying files, branches, commits, pushes, or PRs

### Implementer

The implementer receives the issue URL and planner handoff plan. It is told to:

- inspect the issue with `gh`
- create a branch in its isolated worktree
- make the code changes
- run appropriate checks
- commit and push
- open a PR
- return only the PR id or PR URL

### Judge

Each judge receives the issue URL, PR id, planner handoff, and harness metadata. It can inspect the PR with `git` and `gh`, but must not mutate anything.

Judges score:

| Dimension | Meaning |
|-----------|---------|
| `task_completion` | Does the PR address the issue and avoid unrelated work? |
| `correctness` | Is the behavior likely correct and robust? |
| `code_quality` | Are changes maintainable, idiomatic, and appropriately scoped? |
| `verification` | Were meaningful tests/checks included or run? |

`cost_efficiency` is computed by the harness as quality divided by cost.

---

## Output Layout

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

- Start with `--dry-run`.
- Start real runs with `--conditions one-condition --trials 1`.
- Use `--parallel 1` until you are comfortable with branch/PR behavior.
- Run against a test repository or issue first.
- Expect one PR per implementer attempt.
- Judges are instructed not to mutate PRs, but implementers intentionally do.

---

## Troubleshooting

### `--issue is required`

Real runs require a GitHub issue:

```bash
uv run duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6
```

### `gh CLI is required`

Install and authenticate GitHub CLI:

```bash
gh auth login
gh auth status
```

### Pi cannot find a model

Check `config/models.yaml`. `provider` and `model_id` must match what your Pi installation knows.

### Too many branches/PRs

Use fewer models, fewer trials, explicit `--conditions`, and `--parallel 1`.

---

## Design Docs

- [`DESIGN.md`](DESIGN.md) — design rationale
- [`.exploration/`](.exploration/) — architecture walkthrough generated for this codebase
