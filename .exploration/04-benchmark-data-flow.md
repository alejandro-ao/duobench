# Benchmark Data Flow

This document follows data from the GitHub issue through planning, PR creation, judging, aggregation, charts, and reports.

## End-to-End Data Flow

```text
GitHub issue URL
  ↓
Planner prompt template + local repo/gh exploration
  ↓
plan.md
  ↓
Implementer prompt template + issue URL + plan text
  ↓
isolated git worktree
  ↓
implementer-created branch + commit + pushed PR
  ↓
PR id returned by implementer
  ↓
Judge prompt bundle: issue URL + PR id + plan + metadata
  ↓
judge uses git/gh to review PR
  ↓
per-judge scores
  ↓
aggregate results
  ↓
charts + report.html
```

## Planner Artifacts

```text
runs/<timestamp>/shared-plans/<planner>/trial-<n>/
  plan.md
  shared-plan.json
  planner-transcript.json
  planner-events.jsonl
```

## Condition Trial Artifacts

```text
runs/<timestamp>/conditions/<condition-id>/trial-<n>/
  plan.md
  planner-transcript.json
  planner-events.jsonl
  implementer-transcript.json
  implementer-events.jsonl
  worktree/
  verify.json
  trial.json
  judge-transcripts/
```

`worktree/` is the isolated git worktree where the implementer worked. `verify.json` records PR/worktree metadata; the actual correctness evaluation is done by judges inspecting the PR.

## Transcripts

`src/duobench/transcript.py` stores prompt/response details for each model phase, including full prompt, assistant text, raw Pi messages, usage, cost, and duration.

## Judging

`src/duobench/judge.py` sends the issue URL, PR id, planner handoff, and harness metadata to every configured judge model. Judges have local read/bash tools, so they can run `gh pr view`, `gh pr diff`, `gh issue view`, `git show`, and related commands.

The judged dimensions are:

```python
DIMENSIONS = ("task_completion", "correctness", "code_quality", "verification")
```

## Aggregation

`src/duobench/aggregate.py` takes all `TrialRecord` objects and produces `results.json`.

| Field | Meaning |
|-------|---------|
| `dimensions` | Mean task_completion/correctness/code_quality/verification scores |
| `quality` | Mean of the judged dimensions |
| `cost_usd` | Mean planner + implementer cost |
| `cost_efficiency` | `quality / cost_usd` |
| `self_bias` | Judge × condition score matrix |

Cost efficiency is computed by the harness, not by the judge models.

## Charts and Report

`src/duobench/charts.py` writes PNG/CSV outputs for leaderboard, dimension radar, cost-vs-quality, and self-bias. `src/duobench/report.py` writes `report.html` with transcripts, metrics, and trial metadata.

## Related Documents

- [Architecture Overview](01-architecture-overview.md)
- [Pi RPC Agent Sessions](03-pi-rpc-agent-sessions.md)
- [Configuration and Prompts](05-configuration-and-prompts.md)
