# Pi RPC Agent Sessions

This document explains how `duobench` runs planner, implementer, and judge models through Pi RPC.

## Why Pi RPC Exists Here

`duobench` is model-agnostic. Instead of directly calling Anthropic, OpenAI, Kimi, or another API, it delegates model execution to Pi:

```bash
pi --mode rpc
```

Pi RPC is a JSONL protocol over stdin/stdout. `duobench` sends JSON commands and receives JSON events.

## The PiSession Class

`src/duobench/pi_rpc.py` contains `PiSession`, a context-manager wrapper around a `pi --mode rpc` subprocess.

Important responsibilities:

| Responsibility | How |
|----------------|-----|
| Start Pi | `subprocess.Popen(["pi", "--mode", "rpc", ...])` |
| Select model | send `set_model` RPC command |
| Set thinking level | send `set_thinking_level` RPC command |
| Send prompt | send `prompt` or `follow_up` RPC command |
| Collect result | wait for `agent_end` event |
| Track usage | aggregate assistant `usage` fields |
| Persist raw events | write `*-events.jsonl` when configured |

## Session Startup

`PiSession.__enter__()` builds CLI args roughly like this:

```text
pi --mode rpc [--no-session] [--name NAME] [--no-tools or --tools ...]
```

The planner, implementer, and judge use different tool settings.

## Planner Session

Implemented in `src/duobench/plan_phase.py`.

The planner is allowed to inspect the local repository but should not modify it. It runs with this tool allowlist:

```python
allowed_tools=["read", "grep", "find", "ls", "bash"]
```

The planner prompt asks it to:

- inspect local files as needed,
- produce a concise implementation plan,
- avoid editing files,
- note if an external URL/resource is inaccessible.

The planner writes its final response to:

```text
shared-plans/<planner>/trial-<n>/plan.md
```

## Implementer Session

Implemented in `src/duobench/impl_phase.py`.

The implementer runs in the generated build directory with tools enabled. Its prompt contains:

```text
Complete the following user task:

{user_prompt}

Another agent explored the repository and produced this plan:

{plan}
```

The implementer is told to treat the plan as guidance, verify it independently, make changes, and run checks if possible.

## Multi-turn Implementer Loop

The implementer may not finish after the first response. `run_impl_phase()` checks for completion markers such as:

```text
TASK COMPLETE
implementation complete
build complete
```

If it does not look complete, `duobench` sends follow-up messages like:

```text
Continue working on the task. If anything from the user request or plan is missing...
```

This loop is bounded by `_MAX_FOLLOW_UPS` and the overall wall-clock timeout.

## Judge Sessions

Implemented in `src/duobench/judge.py`.

Each judge runs with tools disabled:

```python
PiSession(cwd=Path.cwd(), enable_tools=False)
```

The judge receives:

- source code collected from the build directory,
- smoke-test summary from Playwright,
- screenshots, when supported by the model/provider.

The judge must return strict JSON with:

```json
{
  "architecture": 1,
  "correctness": 1,
  "visual_ux": 1,
  "notes": "..."
}
```

## Usage and Cost Collection

`PiSession._collect_until_agent_end()` waits until Pi emits `agent_end`. That event contains full message history. `duobench` computes the usage delta since the previous turn so follow-up turns are not double-counted.

```text
agent_end messages
  ↓
assistant usage fields
  ↓
Usage(input, output, cache_read, cache_write, reported_cost)
  ↓
compute_cost() using models.yaml pricing
```

## Safety Detail: Git Ceiling

When starting Pi, `PiSession` sets `GIT_CEILING_DIRECTORIES` so agents running from generated run/build directories do not accidentally discover and mutate the harness repo's Git state.

## Related Documents

- [CLI and Run Flow](02-cli-and-run-flow.md)
- [Configuration and Prompts](05-configuration-and-prompts.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
