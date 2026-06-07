# Benchmark Data Flow

This document follows data from the original prompt through planning, implementation, verification, judging, aggregation, charts, and reports.

## End-to-End Data Flow

```text
User prompt
  ↓
Planner prompt template + local repo exploration
  ↓
plan.md
  ↓
Implementer prompt template + plan text
  ↓
build/ files
  ↓
Playwright verification + screenshots
  ↓
Judge prompt bundle: source + smoke summary + screenshots
  ↓
per-judge scores
  ↓
aggregate results
  ↓
charts + report.html
```

## Planner Artifacts

Shared planner outputs live under:

```text
runs/<timestamp>/shared-plans/<planner>/trial-<n>/
  plan.md
  shared-plan.json
  planner-transcript.json
  planner-events.jsonl
```

The important handoff artifact is `plan.md`. The transcript and event log are for inspection/debugging.

## Condition Trial Artifacts

Each planner × implementer condition and trial gets its own directory:

```text
runs/<timestamp>/conditions/<condition-id>/trial-<n>/
  plan.md
  planner-transcript.json
  planner-events.jsonl
  implementer-transcript.json
  implementer-events.jsonl
  build/
  screenshots/
  verify.json
  trial.json
  judge-transcripts/
```

## Transcripts

`src/duobench/transcript.py` stores prompt/response details for each model phase.

A transcript turn includes:

| Field | Meaning |
|-------|---------|
| `kind` | `prompt`, `follow_up`, or dry-run marker |
| `prompt` | Full prompt sent to the model |
| `assistant_text` | Final assistant text for that turn |
| `messages` | Raw Pi message objects for the turn |
| `usage` | Input/output/cache tokens and Pi-reported cost |
| `cost` | Configured benchmark cost from `models.yaml` |
| `duration_s` | Turn duration |

`transcript_stats()` derives totals such as number of turns, messages, tool calls, tokens, and USD.

## Verification

`src/duobench/verify.py` uses Playwright to load the generated `build/index.html` through `file://`.

It records:

- whether desktop markup rendered,
- whether taskbar markup rendered,
- fatal console/page errors,
- launchable app candidates,
- how many apps opened windows,
- screenshots.

The result is written to `verify.json` and summarized for judges with `VerifyResult.summary_for_judge()`.

## Judging

`src/duobench/judge.py` collects source files from the build directory, combines them with smoke-test results, and sends them to every configured judge model.

The judged dimensions are defined in `DIMENSIONS`:

```python
DIMENSIONS = ("architecture", "correctness", "visual_ux")
```

Each judge returns integer scores from 1 to 10. `average_dimensions()` averages valid judge scores for the trial record.

## Aggregation

`src/duobench/aggregate.py` takes all `TrialRecord` objects and produces `results.json`.

Important computed fields:

| Field | Meaning |
|-------|---------|
| `dimensions` | Mean architecture/correctness/visual_ux scores |
| `quality` | Mean of the three judged dimensions |
| `cost_usd` | Mean planner + implementer cost |
| `cost_efficiency` | `quality / cost_usd` |
| `self_bias` | Judge × condition score matrix |

Cost efficiency is intentionally computed by the harness, not by the judge models.

## Charts

`src/duobench/charts.py` writes both PNG and CSV outputs:

| Chart | Purpose |
|-------|---------|
| `leaderboard.png/.csv` | Quality ranking |
| `dimension-radar.png/.csv` | Architecture/correctness/visual UX profile |
| `cost-vs-quality.png/.csv` | Main cost/quality trade-off chart |
| `self-bias-matrix.png/.csv` | Judge score heatmap |

## Report

`src/duobench/report.py` generates `report.html`.

The report embeds or links:

- leaderboard summary,
- generated build iframe,
- screenshots,
- planner transcript,
- implementer transcript,
- judge transcripts,
- timing/token/cost metrics.

## Related Documents

- [Architecture Overview](01-architecture-overview.md)
- [Pi RPC Agent Sessions](03-pi-rpc-agent-sessions.md)
- [Configuration and Prompts](05-configuration-and-prompts.md)
