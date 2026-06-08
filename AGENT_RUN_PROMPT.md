# Prompt for a cloud coding agent

Use this prompt when asking a cloud agent/runner to execute this benchmark.

```text
You are operating in a cloud machine. Your task is to run the duobench benchmark and return the generated artifacts, especially the HTML report.

Repository:
  git@github.com:alejandro-ao/agent-synergy-eval.git

Goal:
  Run exactly one real benchmark condition first: GPT 5.5 as planner and Kimi K2.6 as implementer (`gpt-x-kimi`), one trial. Do not run the full matrix unless explicitly asked later.

Hard requirement:
  You MUST run the real benchmark inside tmux (or an equivalent persistent terminal multiplexer if tmux is unavailable). Do not run the real benchmark directly in a short-lived shell, because it can take a long time and may be interrupted. Use plain logs (`--no-live`) and tee output to a log file.

Important context:
  - This project benchmarks planner × implementer LLM pairings through Pi RPC.
  - The planner receives `prompts/architect.md` and produces `plan.md`.
  - The implementer receives `prompts/implement.md` with `{plan}` replaced by the planner output and writes a small MiniDesk browser app into `build/`. **By default, `--local-commit` is on**: the implementer must create a single local commit and return its SHA. The harness installs safety wrappers (PATH-prepended `git`/`gh` rejecting `git push` and `gh pr create`) and removes the `upstream` remote, so the agent cannot push branches or open PRs against the upstream repository. Do not pass `--no-local-commit` unless you intentionally want external PRs.
  - Judges score the build from source, screenshots, and smoke-test output. In local-commit mode the judge prompt asks the judge to inspect the commit, diff, and worktree state instead of a PR.
  - The final review artifact is `runs/<timestamp>/report.html`.
  - Raw transcripts/events are saved under each trial directory.

Setup steps:
  1. Clone the repo.
  2. Ensure `uv` is installed.
  3. Run:
       uv sync
       uv run playwright install chromium
  4. Ensure the `pi` binary is available on PATH and can run `pi --mode rpc`.
  5. Ensure Pi has the required providers/models configured:
       - provider `openai-codex`, model `gpt-5.5`
       - provider `kimi-coding`, model `kimi-for-coding`
     If those provider/model IDs are wrong for the environment, update `config/models.yaml` accordingly and explain the change.

Validation:
  First run a dry run:
    uv run duobench run --dry-run --conditions gpt-x-kimi --trials 1 --no-live

Real run:
  Run the real benchmark inside tmux. Use this exact pattern, replacing `<repo>` with the repository path:

  tmux new-session -d -s duobench 'cd <repo> && PYTHONUNBUFFERED=1 uv run duobench run --conditions gpt-x-kimi --trials 1 --no-live --plan-timeout 600 --impl-timeout 1800 --judge-timeout 300 2>&1 | tee /tmp/duobench.log'

  Monitor it with:
    tmux attach -t duobench
    tail -f /tmp/duobench.log

  Detach safely from tmux with Ctrl-b, then d. Do NOT press Ctrl-d unless you intend to close the shell/session.

  If tmux is truly unavailable, use an equivalent persistent background/session mechanism and explain what you used.

Do not accidentally run all conditions. Use `--conditions gpt-x-kimi`.

When complete, report:
  - run directory path, e.g. `runs/2026-...`
  - `report.html` path
  - leaderboard summary printed by the CLI
  - whether `verify.json` says `boots_ok: true`
  - total configured cost from `results.json`
  - any failures/errors/timeouts

Artifacts to preserve/return:
  - `runs/<timestamp>/report.html`
  - `runs/<timestamp>/results.json`
  - `runs/<timestamp>/results/`
  - the whole `runs/<timestamp>/conditions/gpt-x-kimi/trial-0/` directory if possible

Do not commit generated run artifacts unless explicitly asked. Canonical outputs stay under `runs/<timestamp>/`; do not push generated artifacts unless asked.

If anything fails:
  - rerun with `--debug` only if necessary
  - inspect `planner-events.jsonl`, `implementer-events.jsonl`, and transcript JSON files if they exist
  - explain exactly which phase failed: config, planner, implementer, verify, judge, charts, or report generation
```
