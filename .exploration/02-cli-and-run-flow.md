# CLI and Run Flow

This document explains how the `duobench` command starts and how `run.py` orchestrates the GitHub issue → PR benchmark.

## CLI Entry Point

The installed command is defined in `pyproject.toml`:

```toml
[project.scripts]
duobench = "duobench.run:main"
```

That calls `main()` in `src/duobench/run.py`.

## Commands

| Command | Purpose |
|---------|---------|
| `duobench run ...` | Run a benchmark |
| `duobench report RUN_DIR` | Regenerate `report.html` for an existing run |

Shorthand is supported:

```bash
duobench --issue https://github.com/org/repo/issues/123 --models kimi-k2.6,gpt-5.5 --trials 1
```

## Important Run Flags

| Flag | Meaning |
|------|---------|
| `--issue URL` | GitHub issue URL/reference; required for real runs |
| `--models a,b,c` | Build a full planner × implementer matrix |
| `--planners a,b --implementers c,d` | Build a rectangular matrix |
| `--conditions ids` | Use explicit condition IDs from `conditions.yaml` |
| `--trials N` | Repeated trials per condition |
| `--dry-run` | Stub model calls and generate synthetic artifacts |
| `--parallel auto\|all\|N` | Planner/build concurrency control |
| `--pi-sessions / --no-pi-sessions` | Persist Pi sessions for inspection |

Real runs require a git repository and authenticated `gh` CLI because agents fetch issues and create PRs themselves.

## Run Flow in `run.py`

```text
_main()
  ↓
parse args
  ↓
load_config()
  ↓
select_run_conditions()
  ↓
load GitHub issue URL + prompt templates
  ↓
create runs/<timestamp>/
  ↓
prepare_shared_plans()
  ↓
run_condition_trials()
    └─ create isolated git worktree per condition/trial
    └─ implementer opens PR and returns PR id
  ↓
judge_panel() for each PR
  ↓
aggregate()
  ↓
generate_charts()
  ↓
generate_report()
```

## Phase 1: Shared Planning

`prepare_shared_plans()` creates one planner job per unique planner per trial. Each planner is asked to inspect the issue with `gh`, inspect the local repository, and produce `plan.md`. It must not modify files.

## Phase 2: Implementation + PR Creation

`run_condition_trials()` creates one job per condition per trial. Each real job:

1. Copies the shared plan artifact into the trial directory.
2. Creates an isolated git worktree under the trial directory.
3. Runs the implementer Pi session inside that worktree.
4. The implementer inspects the issue, creates a branch, changes code, commits, pushes, opens a PR, and returns only the PR id.
5. The harness records the PR id and worktree metadata in `verify.json` / `trial.json`.

## Phase 3: Judging

After all PRs are produced, the harness runs `judge_panel()` for every trial. Judges receive the issue URL, PR id, planner handoff, and harness metadata. They can use local git and `gh` to inspect the issue and PR, but are instructed not to mutate anything.

## Related Documents

- [Architecture Overview](01-architecture-overview.md)
- [Configuration and Prompts](05-configuration-and-prompts.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
