# duobench Exploration Docs

Beginner-friendly documentation for the `duobench` CLI and benchmark architecture.

## Document List

| # | Document | Description |
|---|----------|-------------|
| 01 | [Architecture Overview](01-architecture-overview.md) | Big-picture system design and module map |
| 02 | [CLI and Run Flow](02-cli-and-run-flow.md) | How `duobench` starts, parses flags, and orchestrates phases |
| 03 | [Pi RPC Agent Sessions](03-pi-rpc-agent-sessions.md) | How planner, implementer, and judges are run through Pi RPC |
| 04 | [Benchmark Data Flow](04-benchmark-data-flow.md) | Artifacts, transcripts, verification, scoring, charts, and report output |
| 05 | [Configuration and Prompts](05-configuration-and-prompts.md) | Models, conditions, judges, user prompts, and packaged defaults |

## Recommended Reading Order

Start with the architecture overview, then the CLI/run flow. After that, read Pi RPC if you want to understand model execution, or configuration/prompts if you want to run a new experiment.
