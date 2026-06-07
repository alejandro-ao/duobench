# Pi RPC Agent Sessions

This document explains how `duobench` runs planner, implementer, and judge models through Pi RPC.

## Why Pi RPC Exists Here

`duobench` delegates model execution to Pi:

```bash
pi --mode rpc
```

Pi RPC is a JSONL protocol over stdin/stdout. `src/duobench/pi_rpc.py` wraps this protocol in `PiSession`.

## PiSession Responsibilities

| Responsibility | How |
|----------------|-----|
| Start Pi | `subprocess.Popen(["pi", "--mode", "rpc", ...])` |
| Select model | send `set_model` RPC command |
| Set thinking level | send `set_thinking_level` RPC command |
| Send prompt | send `prompt` or `follow_up` RPC command |
| Collect result | wait for `agent_end` event |
| Track usage | aggregate assistant `usage` fields |
| Persist raw events | write `*-events.jsonl` when configured |

## Planner Session

Implemented in `src/duobench/plan_phase.py`.

The planner runs in the repository and gets read/local inspection tools:

```python
allowed_tools=["read", "grep", "find", "ls", "bash"]
```

It is expected to use `gh` through bash to inspect the issue, but not to modify files, create branches, commits, pushes, or PRs.

## Implementer Session

Implemented in `src/duobench/impl_phase.py`.

The implementer runs inside an isolated git worktree created by `run.py`. Its prompt tells it to:

1. inspect the GitHub issue with `gh`,
2. create a branch,
3. make code changes,
4. run checks,
5. commit,
6. push,
7. create a PR,
8. return only the PR id.

`impl_phase.py` extracts a PR id from the final response, accepting either a PR number or GitHub PR URL.

## Judge Sessions

Implemented in `src/duobench/judge.py`.

Judges get read/local inspection tools and are instructed to use git and `gh` to inspect the issue and PR. They must not comment, review, merge, close, push, or mutate the PR.

Judges return strict JSON scores for:

```python
DIMENSIONS = ("task_completion", "correctness", "code_quality", "verification")
```

## Usage and Cost Collection

`PiSession._collect_until_agent_end()` waits until Pi emits `agent_end`, aggregates assistant usage, and returns only the usage delta for the current turn. `src/duobench/cost.py` converts that usage to USD using `models.yaml` pricing.

## Related Documents

- [CLI and Run Flow](02-cli-and-run-flow.md)
- [Configuration and Prompts](05-configuration-and-prompts.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
