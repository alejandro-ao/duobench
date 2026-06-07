# Configuration and Prompts

This document explains how `duobench` is configured and how its GitHub issue / PR prompts are assembled.

## Configuration Files

```text
config/models.yaml
config/conditions.yaml
```

Installed/package defaults also exist under:

```text
src/duobench/defaults/config/
src/duobench/defaults/prompts/
```

If default CLI paths are missing in the current directory, `duobench` falls back to packaged defaults.

## Models

`src/duobench/config.py` loads models into:

```python
@dataclass(frozen=True)
class Model:
    key: str
    provider: str
    model_id: str
    pricing: Pricing
    thinking_level: str | None = None
```

The `provider` and `model_id` are passed directly to Pi RPC `set_model`.

## Conditions

Conditions are planner × implementer pairs:

```python
@dataclass(frozen=True)
class Condition:
    id: str
    planner: str
    implementer: str
```

They can come from `conditions.yaml`, or be generated from `--models`, `--planners`, and `--implementers`.

## GitHub Issue Input

Real runs require a GitHub issue:

```bash
duobench --issue https://github.com/org/repo/issues/123 --models kimi,gpt --trials 1
```

The harness does not parse the issue. Agents must use `gh` themselves.

## Prompt Templates

Prompt templates live in:

```text
prompts/architect.md
prompts/implement.md
prompts/judge.md
```

and packaged defaults live in:

```text
src/duobench/defaults/prompts/
```

### Planner prompt

Uses:

```text
{issue_url}
```

The planner should inspect the issue/repo using local tools and `gh`, then return only a plan. It must not modify files or create branches/PRs.

### Implementer prompt

Uses:

```text
{issue_url}
{plan}
```

The implementer must inspect the issue, create a branch, change code, test, commit, push, open a PR, and return only the PR id.

### Judge prompt

Uses:

```text
{issue_url}
{pr_id}
{plan}
{smoke_results}
```

The judge uses git and `gh` to inspect the issue/PR and returns strict JSON scores for `task_completion`, `correctness`, `code_quality`, and `verification`.

## Prompt Formatting Code

`src/duobench/run.py` uses `_format_prompt_template()` to substitute placeholders. If a template references an unknown placeholder, it raises a `ConfigError`.

## Related Documents

- [CLI and Run Flow](02-cli-and-run-flow.md)
- [Pi RPC Agent Sessions](03-pi-rpc-agent-sessions.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
