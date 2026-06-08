# Prompt for a cloud coding agent

Use this prompt when asking a cloud agent/runner to execute this benchmark.
The agent is the orchestrator: there is no monolithic CLI. It launches one Pi RPC
instance per phase-unit via `scripts/run_phase.py` (each writes a `result.json`
sentinel), gates each phase on completion, then aggregates and plots.

The canonical orchestration contract is the **`duobench` skill** at
`.claude/skills/duobench/SKILL.md` — when running inside Claude Code, follow it.
For a non-Claude runner, the prompt below covers the same flow.

```text
You are operating in a cloud machine. Your task is to run the duobench benchmark and return the artifacts (results.json and the plots under runs/<timestamp>/results/).

Repository:
  git@github.com:alejandro-ao/agent-synergy-eval.git

Goal:
  Run exactly one real condition first: GPT 5.5 as planner and Kimi K2.6 as implementer (condition id `gpt-5.5-x-kimi-k2.6`), one trial. Do not run the full matrix unless explicitly asked later.

Hard requirement:
  Run each real phase job inside tmux (or an equivalent persistent multiplexer); jobs can take a long time. Redirect each job's output to a log file. A job is finished when its result.json appears in its --out-dir.

Important context:
  - duobench benchmarks planner × implementer LLM pairings through Pi RPC.
  - The planner receives prompts/architect.md and produces plan.md.
  - The implementer receives prompts/implement_local_commit.md (with {plan} substituted), works in an isolated git worktree, and creates exactly ONE local commit, returning its SHA. The harness installs PATH-prepended git/gh safety wrappers (rejecting `git push` and `gh pr create`) and removes the `upstream` remote, so the agent cannot push branches or open PRs. Submission mode `local_commit` is the default; only pass `--submission-mode pr` if you intentionally want external PRs.
  - Judges receive prompts/judge_local_commit.md and inspect the commit, diff, and worktree state read-only, scoring 4 dimensions as strict JSON.
  - Final artifacts are runs/<timestamp>/results.json and runs/<timestamp>/results/*.png.

Setup:
  1. Clone the repo; ensure `uv`, `git`, authenticated `gh`, and `pi` (can run `pi --mode rpc`) are available.
  2. uv sync
  3. Ensure Pi has the providers/models: provider `openai-codex` model `gpt-5.5`, provider `kimi-coding` model `kimi-for-coding`. If different, update config/models.yaml and explain.

Run (TS = a UTC timestamp like 2026-06-08T10-30-00; ISSUE = the issue URL):
  COND=gpt-5.5-x-kimi-k2.6

  # 1) plan job for the planner (gpt-5.5)
  tmux new-session -d -s duobench_plan \
    "cd <repo> && PYTHONUNBUFFERED=1 uv run python scripts/run_phase.py --phase plan \
       --run-dir runs/$TS --out-dir runs/$TS/shared-plans/gpt-5.5/trial-0 \
       --issue $ISSUE --planner gpt-5.5 --trial 0 \
       > runs/$TS/shared-plans/gpt-5.5/trial-0/job.log 2>&1"
  # wait until runs/$TS/shared-plans/gpt-5.5/trial-0/result.json exists

  # 2) implement job (reads the plan above)
  tmux new-session -d -s duobench_impl \
    "cd <repo> && PYTHONUNBUFFERED=1 uv run python scripts/run_phase.py --phase implement \
       --run-dir runs/$TS --out-dir runs/$TS/conditions/$COND/trial-0 --condition $COND \
       --issue $ISSUE --planner gpt-5.5 --implementer kimi-k2.6 \
       --plan-path runs/$TS/shared-plans/gpt-5.5/trial-0/plan.md --trial 0 \
       > runs/$TS/conditions/$COND/trial-0/job.log 2>&1"
  # wait for runs/$TS/conditions/$COND/trial-0/result.json; read its artifact.commit_sha as SHA

  # 3) judge jobs (one per judge: kimi-k2.6, gpt-5.5)
  for J in kimi-k2.6 gpt-5.5; do
    tmux new-session -d -s duobench_judge_$J \
      "cd <repo> && PYTHONUNBUFFERED=1 uv run python scripts/run_phase.py --phase judge \
         --run-dir runs/$TS --out-dir runs/$TS/conditions/$COND/trial-0 --condition $COND \
         --issue $ISSUE --judge-key $J \
         --build-dir runs/$TS/conditions/$COND/trial-0/worktree --commit-sha <SHA> --trial 0 \
         > runs/$TS/conditions/$COND/trial-0/job-judge-$J.log 2>&1"
  done
  # wait for runs/$TS/conditions/$COND/trial-0/results/judge-*.json

  # 4) aggregate + plot (pure, fast — no tmux needed)
  uv run python scripts/aggregate.py runs/$TS
  cp scripts/plots_example.py runs/$TS/plots.py && uv run python runs/$TS/plots.py runs/$TS

Monitor a job: tmux attach -t <session> (detach with Ctrl-b then d), or tail -f the job.log.

When complete, report:
  - run directory path, e.g. runs/2026-...
  - the leaderboard printed by scripts/aggregate.py
  - each job's result.json status (complete/timeout/stalled/error)
  - total cost from results.json
  - any failures/errors/timeouts

Artifacts to preserve/return:
  - runs/<timestamp>/results.json
  - runs/<timestamp>/results/ (PNGs + CSVs)
  - runs/<timestamp>/conditions/$COND/trial-0/ if possible

Do not commit generated run artifacts unless explicitly asked.

If anything fails:
  - read the failing job's result.json (status + error + notes) and its job.log tail
  - inspect planner-events.jsonl / implementer-events.jsonl / transcript JSON if present
  - state exactly which phase/unit failed: plan, implement, judge, or aggregate
```
