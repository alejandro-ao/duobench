# Configuration and Prompts

This document explains how `duobench` is configured and how the planner/implementer prompts are assembled.

## Configuration Files

There are two YAML config files:

```text
config/models.yaml
config/conditions.yaml
```

Installed/package defaults also exist under:

```text
src/duobench/defaults/config/
src/duobench/defaults/prompts/
```

If the CLI default paths are missing in the current directory, `duobench` falls back to packaged defaults. This allows installed `duobench` to run from another experiment directory.

## Models

`src/duobench/config.py` loads models into this dataclass:

```python
@dataclass(frozen=True)
class Model:
    key: str
    provider: str
    model_id: str
    pricing: Pricing
    thinking_level: str | None = None
```

Example YAML shape:

```yaml
models:
  kimi-k2.6:
    provider: kimi-coding
    model_id: kimi-for-coding
    thinking: high
    pricing: { input: 0.95, output: 4.00 }
judges:
  - kimi-k2.6
```

The `provider` and `model_id` are passed directly to Pi RPC `set_model`.

## Pricing

Pricing is represented as dollars per million tokens:

```python
@dataclass(frozen=True)
class Pricing:
    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None
```

`src/duobench/cost.py` computes benchmark cost from the configured rates. Pi/provider-reported cost is preserved separately for auditing, but configured pricing is the benchmark source of truth.

## Conditions

Conditions are explicit planner × implementer pairs:

```python
@dataclass(frozen=True)
class Condition:
    id: str
    planner: str
    implementer: str
```

They can come from `conditions.yaml`, or be generated from CLI flags such as `--models`, `--planners`, and `--implementers`.

## Fail-fast Validation

`load_config()` validates that:

- `models` is a non-empty mapping,
- every model has `provider`, `model_id`, and `pricing`,
- `judges` is a non-empty list,
- every judge key exists in `models`,
- every condition planner/implementer key exists in `models`,
- thinking levels are one of `off`, `minimal`, `low`, `medium`, `high`, `xhigh`.

This catches config mistakes before any model/API calls are made.

## User Prompt

The benchmark now starts from one realistic user task prompt.

You can provide it inline:

```bash
duobench --prompt 'fix the issue described here: ...' --models kimi,gpt --trials 1
```

or from a file:

```bash
duobench --prompt-file issue.md --models kimi,gpt --trials 1
```

If neither is provided, `DEFAULT_USER_PROMPT` in `src/duobench/run.py` uses the MiniDesk app task for backwards compatibility.

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

The planner template includes:

```text
User task:

{user_prompt}
```

It asks the planner to inspect the local repository, produce a concise implementation plan, and avoid modifying files.

Important detail: no web access is bundled. If the user prompt references an external URL, the planner is told to note that the content is inaccessible and proceed from local context.

### Implementer prompt

The implementer template includes both placeholders:

```text
{user_prompt}
{plan}
```

It tells the implementer to use the plan as guidance but verify it independently.

### Judge prompt

The judge prompt uses source and smoke-test placeholders:

```text
{source}
{smoke_results}
```

`judge.py` replaces those before sending the prompt to each judge model.

## Prompt Formatting Code

`src/duobench/run.py` uses `_format_prompt_template()` to substitute placeholders. If a template references an unknown placeholder, the function raises a `ConfigError` with a clear message.

## Related Documents

- [CLI and Run Flow](02-cli-and-run-flow.md)
- [Pi RPC Agent Sessions](03-pi-rpc-agent-sessions.md)
- [Benchmark Data Flow](04-benchmark-data-flow.md)
