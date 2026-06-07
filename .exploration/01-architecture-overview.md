# Architecture Overview

This document explains the high-level architecture of `duobench`, a Python CLI that benchmarks planner × implementer AI coding-agent pairings through Pi RPC.

## What the Tool Does

`duobench` takes a user task prompt, asks one or more planner models to inspect the local repository and write a plan, then asks implementer models to complete the task from that plan. Each result is verified, judged, aggregated, charted, and written into a timestamped run directory.

The harness itself is deterministic Python. The only agentic work happens inside spawned Pi RPC sessions.

## Main Architecture

```text
User CLI command
  ↓
src/duobench/run.py
  ↓
load config + prompts
  ↓
shared planner phase          one run per unique planner × trial
  ↓
implementation phase          one run per planner × implementer condition × trial
  ↓
verification                  Playwright smoke checks + screenshots
  ↓
judge panel                   model judges score every build
  ↓
aggregation + charts + report results
```

## Key Design Ideas

### 1. Planner and implementer are separate sessions

The planner does not directly control the implementer. The planner only produces text: `plan.md`. The implementer gets the original user task plus this plan.

```text
Planner Pi session
  └─ produces plan.md
        ↓
Fresh implementer Pi session
  └─ receives user task + plan.md text
```

This makes the benchmark about handoff quality, not one continuous conversation.

### 2. Shared plans avoid repeated planner cost

For matrix runs, each unique planner runs once per trial. Its plan is reused for every implementer paired with that planner.

Example with models A, B, C and one trial:

```text
Planner runs:      A, B, C                  = 3 plans
Implementation:    A×A A×B A×C ... C×C      = 9 builds
```

### 3. Pi is the uniform model substrate

All models run through Pi RPC. `duobench` does not special-case Anthropic, OpenAI, Kimi, etc. It just sends Pi:

```json
{"type": "set_model", "provider": "...", "modelId": "..."}
{"type": "prompt", "message": "..."}
```

### 4. Outputs are complete and inspectable

Every run writes transcripts, raw events, build files, screenshots, judge transcripts, `results.json`, CSVs, PNG charts, and `report.html`.

## Module Map

| File | Purpose |
|------|---------|
| `src/duobench/run.py` | Main CLI orchestrator; selects conditions, runs phases, writes final outputs |
| `src/duobench/pi_rpc.py` | JSONL subprocess client for `pi --mode rpc` |
| `src/duobench/plan_phase.py` | Runs planner Pi session and writes `plan.md` |
| `src/duobench/impl_phase.py` | Runs implementer Pi session with tools enabled |
| `src/duobench/verify.py` | Playwright smoke verification and screenshots |
| `src/duobench/judge.py` | Judge model panel and score parsing |
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
