# CLI and Run Flow

This document explains how the `duobench` command starts and how `run.py` orchestrates a benchmark.

## CLI Entry Point

The installed command is defined in `pyproject.toml`:

```toml
[project.scripts]
duobench = "duobench.run:main"
```

That calls `main()` in `src/duobench/run.py`, which wraps `_main()` with friendly error handling.

## Commands

`duobench` has two subcommands:

| Command | Purpose |
|---------|---------|
| `duobench run ...` | Run a benchmark |
| `duobench report RUN_DIR` | Regenerate `report.html` for an existing run |

There is also shorthand support: if the first argument is not `run` or `report`, `run.py` inserts `run` automatically. This allows:

```bash
duobench --prompt 'fix this bug' --models kimi-k2.6,gpt-5.5 --trials 1
```

instead of:

```bash
duobench run --prompt 'fix this bug' --models kimi-k2.6,gpt-5.5 --trials 1
```

## Important Run Flags

| Flag | Meaning |
|------|---------|
| `--prompt TEXT` | User task sent to every planner |
| `--prompt-file PATH` | Load the user task from a file |
| `--models a,b,c` | Build a full planner × implementer matrix |
| `--planners a,b --implementers c,d` | Build a rectangular matrix |
| `--conditions ids` | Use explicit condition IDs from `conditions.yaml` |
| `--trials N` | Repeated trials per condition |
| `--dry-run` | Stub model calls and generate synthetic artifacts |
| `--parallel auto\|all\|N` | Planner/build concurrency control |
| `--pi-sessions / --no-pi-sessions` | Persist Pi sessions for inspection |

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
load user prompt + prompt templates
  ↓
create runs/<timestamp>/
  ↓
prepare_shared_plans()
  ↓
run_condition_trials()
  ↓
judge_panel() for each build
  ↓
aggregate()
  ↓
generate_charts()
  ↓
generate_report()
```

## Condition Selection

The function `select_run_conditions()` resolves CLI selection into concrete `Condition` objects.

### Full matrix

```bash
duobench run --models a,b,c
```

creates:

```text
a-solo
a-x-b
a-x-c
b-x-a
b-solo
b-x-c
c-x-a
c-x-b
c-solo
```

### Rectangular matrix

```bash
duobench run --planners cheap,strong --implementers strong
```

creates only:

```text
cheap-x-strong
strong-solo
```

### Explicit conditions

```bash
duobench run --conditions kimi-solo,gpt-x-kimi
```

uses rows already defined in `config/conditions.yaml`.

## Phase 1: Shared Planning

`prepare_shared_plans()` creates one planner job per unique planner per trial. Each job calls `run_shared_plan()`, which either:

- creates a synthetic plan in dry-run mode, or
- calls `run_plan_phase()` to spawn a real Pi RPC planner session.

The output is a `SharedPlan` dataclass:

```python
@dataclass(frozen=True)
class SharedPlan:
    planner: str
    trial: int
    plan_text: str
    cost_usd: float
    source_dir: Path
```

## Phase 2: Implementation + Verification

`run_condition_trials()` creates one job per condition per trial. Each job:

1. Copies shared plan artifacts into the condition trial directory.
2. Runs `run_impl_phase()` or creates a synthetic dry-run build.
3. Runs `verify_build()` with Playwright.
4. Writes `verify.json` and `trial.json`.

## Phase 3: Judging

After all builds are produced, the harness loops over every trial record and runs `judge_panel()`. Each judge scores architecture, correctness, and visual UX.

Cost efficiency is not judged by models; it is computed later by `aggregate()`.

## Related Documents

- [Architecture Overview](01-architecture-overview.md)
- [Configuration and Prompts](05-configuration-and-prompts.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
