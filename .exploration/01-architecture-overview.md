# Architecture Overview

This document explains the high-level architecture of `duobench`, a Python CLI that benchmarks planner × implementer AI coding-agent pairings through a GitHub issue → pull request workflow.

## What the Tool Does

`duobench` takes a GitHub issue URL/reference, asks planner models to inspect the issue and local repository, then asks implementer models to fix the issue in isolated git worktrees and open pull requests. Each implementer returns only a PR id. Judge models then inspect the issue/PR with git and `gh`, score the solution, and the harness aggregates costs, charts, and reports.

The harness itself is deterministic Python. The agentic work happens inside spawned Pi RPC sessions.

## Main Architecture

```text
GitHub issue input
  ↓
src/duobench/run.py
  ↓
load config + issue-centered prompt templates
  ↓
shared planner phase          one run per unique planner × trial
  ↓
implementation phase          one isolated git worktree per condition × trial
  ↓
PR creation                   implementer commits, pushes, opens PR, returns PR id
  ↓
judge panel                   judges inspect issue/PR using git + gh
  ↓
aggregation + charts + report results
```

## Key Design Ideas

### 1. The harness does not parse the issue

The planner, implementer, and judge are responsible for using `gh` to inspect the GitHub issue/PR. The harness only passes the issue URL and records artifacts.

### 2. Planner and implementer are separate sessions

The planner only produces text: `plan.md`. The implementer receives the issue URL plus this plan in a fresh Pi session.

```text
Planner Pi session
  └─ inspects issue/repo and produces plan.md
        ↓
Fresh implementer Pi session in a worktree
  └─ fixes issue, commits, pushes, opens PR, returns PR id
```

### 3. Shared plans avoid repeated planner cost

For matrix runs, each unique planner runs once per trial. Its plan is reused for every implementer paired with that planner.

### 4. Pi is the uniform model substrate

All models run through Pi RPC. `duobench` does not special-case Anthropic, OpenAI, Kimi, etc. It sends Pi `set_model`, optional `set_thinking_level`, and prompts.

### 5. Outputs are inspectable

Every run writes transcripts, raw Pi events, worktree metadata, judge transcripts, `results.json`, CSVs, PNG charts, and `report.html`.

## Module Map

| File | Purpose |
|------|---------|
| `src/duobench/run.py` | Main CLI orchestrator; selects conditions, creates worktrees, runs phases |
| `src/duobench/pi_rpc.py` | JSONL subprocess client for `pi --mode rpc` |
| `src/duobench/plan_phase.py` | Runs planner Pi session and writes `plan.md` |
| `src/duobench/impl_phase.py` | Runs implementer Pi session and extracts returned PR id |
| `src/duobench/judge.py` | Judge model panel that can inspect PRs with git/gh |
| `src/duobench/aggregate.py` | Aggregates trial records into final metrics |
| `src/duobench/charts.py` | Generates PNG charts and CSV files |
| `src/duobench/report.py` | Generates `report.html` |
| `src/duobench/config.py` | Loads and validates model/condition YAML |
| `src/duobench/cost.py` | Converts token usage into configured USD cost |
| `src/duobench/transcript.py` | Persists prompts, assistant text, usage, cost, and stats |
| `src/duobench/ui.py` | Optional Rich live dashboard |

## Related Documents

- [CLI and Run Flow](02-cli-and-run-flow.md)
- [Pi RPC Agent Sessions](03-pi-rpc-agent-sessions.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
