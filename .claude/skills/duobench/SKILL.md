---
name: duobench
description: >-
  Benchmark planner×implementer LLM pairings on a real GitHub issue and chart
  quality-per-dollar. Use when the user says things like "benchmark <models> on
  duobench", "run a duobench eval", "add <planner>/<implementer> to the eval",
  "produce plots about the duobench results", or "re-plot the last duobench run".
  You orchestrate plan→implement→judge phase jobs in tmux, aggregate results.json,
  then write seaborn plots from results.json/trial.json.
---

# duobench

duobench measures which **planner LLM × implementer LLM** duo produces the best
**quality-per-dollar** on a real GitHub issue. A planner writes a handoff plan; an
implementer makes ONE local commit fixing the issue (no push, no PR); a panel of
judge LLMs scores each commit on 4 dimensions; cost comes from token usage.

You are the orchestrator. There is no monolithic CLI. You launch thin phase jobs
(`scripts/run_phase.py`, one Pi RPC instance each) across tmux sessions, gate each
phase on completion, aggregate, and plot. Work from the repo root
(`/Users/alejandro/repos/kimi-claude-bench`) with `uv`.

## §0 Operating contract (read first)

- **Strict order:** plan → implement → judge → aggregate → plot. Never start a
  phase until **every** job of the previous phase has written its `result.json`.
- **One tmux job = one Pi instance = one unit of work.** Money phases (plan,
  implement, judge) run in tmux. Short pure steps (aggregate, plotting) run with
  a plain background `Bash`.
- **Never push or open PRs.** Always pass `--submission-mode local_commit` (the
  default). The engine installs git/gh safety wrappers; do not fight them.
- **Confirm before spending.** Show the issue, the resolved condition list, the
  judge panel, trials, and the estimated job count. Wait for a go-ahead.
- **Default to `--trials 1`.**
- **`runs/<ts>/run_state.json` is the source of truth**, not your memory. After
  any uncertainty or context loss, reconstruct state from disk + `tmux ls` —
  never guess which jobs ran.

## §1 Elicit the issue + models

- If the user named models but no issue, **ask for the GitHub issue URL** (accept
  `owner/repo#123` or a full URL). Real runs cannot proceed without it.
- **If the user asks you to pick an issue**, choose one that is: from a public
  repo, **single-commit-fixable**, self-contained, medium-hard, and — crucially —
  has a **known fixing PR/commit** so you can check out the pre-fix base (§1.5).
  Pure-Python repos (Flask, requests, marshmallow…) judge cleanly. Avoid sprawling
  features (hard to score on one commit). Confirm the pick before spending.
- Resolve model names to registry keys in `config/models.yaml`:
  `opus → claude-opus-4.8`, `kimi → kimi-k2.6`, `gpt → gpt-5.5`. If a name is not
  in the registry, warn that it's passed to Pi as a raw `provider/model_id` spec
  with no pricing (`cost_source` becomes `unknown`, so quality-per-dollar is
  unreliable) and confirm.
- Confirm the **judge panel**. Default to the `judges:` list in `config/models.yaml`.
  Offer to add the competing models as judges — multiple judges are averaged per
  build (aggregate auto-discovers every `results/judge-*.json`), and having each
  competitor judge its rivals is what makes the **self-bias chart** meaningful.
  Keep the judge panel/config **identical across runs** you intend to compare, so
  quality is measured by the same instrument.

## §1.5 Issue from ANOTHER repo (SWE-bench style) — READ if the issue isn't this repo

The engine worktrees **`Path.cwd()`** (`run_phase.py` exposes no `--repo-dir`). So
the implementer commits into a worktree of whatever repo is the current directory.
To benchmark an issue from a *different* repo you must run the phase jobs **from a
clone of that repo**, while still importing duobench + configs from THIS repo:

1. **Clone at the pre-fix base.** base = first parent of the fixing PR's merge:
   ```bash
   gh api repos/<owner>/<repo>/commits/<merge_sha> -q '.parents[0].sha'
   git clone https://github.com/<owner>/<repo>.git ~/repos/duobench-targets/<repo>-<issue>
   git -C ~/repos/duobench-targets/<repo>-<issue> checkout <base_sha>
   ```
2. **Enable worktree config on the clone (REQUIRED — else every implement job dies)**
   with `git config --worktree core.hooksPath` failing:
   ```bash
   git -C <clone> config extensions.worktreeConfig true
   ```
   This repo has it on already; fresh clones do not.
3. **Launch jobs with cwd = the clone, project = this repo, ABSOLUTE config paths**
   (relative `config/*.yaml` would silently fall back to packaged defaults, losing
   your pricing/judges). Pattern for every `run_phase.py` call:
   ```bash
   DUO=/Users/alejandro/repos/kimi-claude-bench ; TGT=<clone>
   cd $TGT && uv run --project $DUO python $DUO/scripts/run_phase.py \
     --models-config $DUO/config/models.yaml --conditions-config $DUO/config/conditions.yaml \
     --run-dir $DUO/runs/$TS --out-dir $DUO/runs/$TS/... --issue '<external issue url>' ...
   ```
   Keep the **run dir, results.json, and plots inside this repo** (`$DUO/runs/$TS`).
4. The `--issue` is the external URL; planner/implementer use `gh` against the
   clone's origin to read it. `local_commit` mode blocks push and strips upstream.

Verified working on `pallets/flask#4041` (base `d8c37f43`).

## §2 Expand the planner×implementer matrix

- A square ask ("benchmark opus and kimi") means both models are planners AND
  implementers → N×N conditions. opus,kimi → 4 conditions.
- **Condition id = `<planner>-solo` if planner==implementer, else
  `<planner>-x-<implementer>`**, each part passed through the safe-name rule
  (alnum + `-_.` kept, everything else → `-`). These ids are the directory names
  and the join key everywhere — compute them exactly. You can confirm them with:

  ```bash
  uv run python -c "from duobench.engine import condition_id_for as c; print(c('claude-opus-4.8','kimi-k2.6'))"
  ```

- **Unique planners** (one plan job each) = the deduped planner column.

Example (opus + kimi): conditions `claude-opus-4.8-solo`, `kimi-k2.6-solo`,
`claude-opus-4.8-x-kimi-k2.6`, `kimi-k2.6-x-claude-opus-4.8`; unique planners
`claude-opus-4.8`, `kimi-k2.6`.

## §3 Create the run dir + state

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%S)
mkdir -p runs/$TS
```

Write `runs/$TS/run_state.json` **before launching anything**:

```json
{
  "run_ts": "<TS>", "issue": "<url>", "submission_mode": "local_commit",
  "trials": 1, "concurrency_cap": 2, "phase": "plan",
  "judges": ["kimi-k2.6", "gpt-5.5"],
  "unique_planners": ["claude-opus-4.8", "kimi-k2.6"],
  "conditions": [
    {"id": "claude-opus-4.8-solo", "planner": "claude-opus-4.8", "implementer": "claude-opus-4.8"},
    {"id": "kimi-k2.6-x-claude-opus-4.8", "planner": "kimi-k2.6", "implementer": "claude-opus-4.8"}
  ],
  "jobs": {}
}
```

Update `phase` and the per-unit `jobs` map (`{session, out_dir, result_path, status}`)
as you go, so a fresh agent can resume.

## §4 Phase ordering & gates

For each phase: launch all its jobs (respecting the concurrency cap), then **block
until every expected `result.json` exists** before the next phase.

1. **Plan** — one job per unique planner × trial →
   `runs/$TS/shared-plans/<planner-safe>/trial-<n>/`.
2. **Implement** — one job per condition × trial →
   `runs/$TS/conditions/<cond_id>/trial-<n>/`. Each `--plan-path` points at its
   planner's `plan.md`.
3. **Judge** — only after all impls are terminal: one job per condition × judge ×
   trial, writing `results/judge-<judge>.json` into the trial dir.
4. **Aggregate** — `uv run python scripts/aggregate.py runs/$TS`.
5. **Plot** — `uv run python scripts/plots_example.py runs/$TS` (see §7).

## §6 tmux recipe

Session name: `duobench__<TS>__<phase>__<unit>` (plan: `<planner>__t<n>`;
implement: `<cond>__t<n>`; judge: `<cond>__<judge>__t<n>`).

The commands below assume the issue is **this** repo. For an issue from another
repo, replace the `cd $PWD && uv run python` prefix with the cwd=clone /
`uv run --project $DUO` / absolute-config form from **§1.5**.

**Launch a plan job:**
```bash
P=claude-paths... # see below
JOB="duobench__${TS}__plan__claude-opus-4.8__t0"
OUT="runs/$TS/shared-plans/claude-opus-4.8/trial-0"
mkdir -p "$OUT"
tmux new-session -d -s "$JOB" \
  "cd $PWD && PYTHONUNBUFFERED=1 uv run python scripts/run_phase.py \
     --phase plan --run-dir runs/$TS --out-dir $OUT \
     --issue '$ISSUE' --planner claude-opus-4.8 --trial 0 \
     > $OUT/job.log 2>&1; echo __DUOBENCH_EXIT=\$? >> $OUT/job.log"
```

**Launch an implement job** (`--plan-path` = that planner's plan.md):
```bash
COND="kimi-k2.6-x-claude-opus-4.8"; OUT="runs/$TS/conditions/$COND/trial-0"
mkdir -p "$OUT"
tmux new-session -d -s "duobench__${TS}__implement__${COND}__t0" \
  "cd $PWD && PYTHONUNBUFFERED=1 uv run python scripts/run_phase.py \
     --phase implement --run-dir runs/$TS --out-dir $OUT --condition $COND \
     --issue '$ISSUE' --planner kimi-k2.6 --implementer claude-opus-4.8 \
     --plan-path runs/$TS/shared-plans/kimi-k2.6/trial-0/plan.md --trial 0 \
     --submission-mode local_commit \
     > $OUT/job.log 2>&1; echo __DUOBENCH_EXIT=\$? >> $OUT/job.log"
```

**Launch a judge job** (`--build-dir` = the trial's worktree; `--commit-sha` from
the implement job's `result.json` `artifact.commit_sha`):
```bash
tmux new-session -d -s "duobench__${TS}__judge__${COND}__gpt-5.5__t0" \
  "cd $PWD && PYTHONUNBUFFERED=1 uv run python scripts/run_phase.py \
     --phase judge --run-dir runs/$TS --out-dir runs/$TS/conditions/$COND/trial-0 \
     --condition $COND --issue '$ISSUE' --judge-key gpt-5.5 \
     --build-dir runs/$TS/conditions/$COND/trial-0/worktree --commit-sha $SHA --trial 0 \
     > runs/$TS/conditions/$COND/trial-0/job.log 2>&1; echo __DUOBENCH_EXIT=\$? >>runs/$TS/conditions/$COND/trial-0/job.log"
```

**Concurrency cap:** default **2** money-jobs at once. Launch up to the cap, then
wait for a free slot. If the user says "run them all in parallel", lift the cap
and warn about cost/rate-limits.

**tmux gotchas (learned the hard way):**
- tmux rewrites `.` → `_` in session names (`claude-opus-4.8` shows as
  `claude-opus-4_8`). **Gate on `result.json`, not session names.** If you must
  grep `tmux ls`, match `"$TS"` then the phase substring — don't assume dots.
- If you write a cap-loop helper in bash, target **macOS bash 3.2**: no `mapfile`
  (use `arr=(); for d in dir/*/; do arr+=("$(basename "$d")"); done`).

**Completion detection / phase gate:** the job's last action is an atomic write of
its `result.json`. Poll roughly every 10s:
- if the expected `result.json` exists → job done; read `.status`.
- if it's missing AND `tmux has-session -t <JOB>` reports the session is gone →
  hard crash; read the tail of `job.log`.
Only advance to the next phase when every expected `result.json` is present.

**Let the user watch:** `tmux attach -t <JOB>` (detach with **Ctrl-b then d**),
`tmux ls` to list duobench jobs, `tail -f <out>/job.log`.

## §7 Plotting

```bash
uv run python scripts/plots_example.py runs/$TS        # run in place — no copy needed
```

This writes `runs/$TS/results/*.png` (+ `.csv`), all styled consistently
(seaborn whitegrid/talk, value labels, despined): **leaderboard**,
**cost-vs-quality** (with iso-efficiency guide lines + a color legend instead of
crowded per-dot labels), **dimensions**, **self-bias** (a *"does each judge favor
its own model?"* own-vs-other bar chart — not the old heatmap), and
**cost-breakdown** (sorted, total-cost labels).

For customization ("correctness vs cost only", "facet by planner", "only opus
conditions"): `cp scripts/plots_example.py runs/$TS/plots.py`, edit, and run
`uv run python runs/$TS/plots.py runs/$TS`. The import self-locates `plot_styles`
(walks up for `scripts/`), so a copied script needs **no** `PYTHONPATH`. The
`plot_styles` loaders return tidy DataFrames with dimension names read
dynamically, so edits are small seaborn changes. Pitfall: don't reuse the
variable name `order` for a local list — later plot blocks reuse the
condition-order list of that name. Never import the removed `duobench.charts`.
Show the user the resulting PNGs.

## §5 Resume / add a condition to an existing run

Trigger: "add <planner>/<implementer> to the eval".
1. Find the target run dir (most recent under `runs/`, or the one named). Read its
   `run_state.json` and `results.json`.
2. Compute the **new** condition id(s) and set-difference against existing
   `conditions/*` dirs. e.g. "add gpt planner and kimi implementer" →
   `gpt-5.5-x-kimi-k2.6`.
3. **Plan reuse:** if `shared-plans/<new-planner>/trial-<n>/plan.md` exists, reuse
   it (run no plan job). Before reusing, sanity-check the planner spec recorded in
   that dir's `shared-plan.json` matches the requested model. If absent, run one
   plan job for the new planner.
4. Run the new condition's implement + judge jobs (same tmux recipe).
5. Re-aggregate the whole run dir (`scripts/aggregate.py runs/<ts>` rescans all
   trials, merging old + new) and re-plot. The new condition appears in every
   chart with its stable per-model color.

## Failure & partial runs

- **All implement jobs error instantly** with `git config --worktree ... fatal:
  --worktree cannot be used with multiple working trees unless extensions.
  worktreeConfig is enabled` → the (usually freshly cloned) repo lacks worktree
  config. Fix: `git -C <repo> config extensions.worktreeConfig true`, then delete
  the failed `result.json` + `worktree/` dirs, `git -C <repo> worktree prune`, and
  relaunch implement. (See §1.5.)
- **Plan job fails** → block the implement jobs that depend on that plan; run the
  others; offer to retry just that plan job.
- **Implement `timeout`/`stalled`/`stopped`** → a valid data point (flows to
  `impl_status` → leaderboard). Still judge it; annotate non-complete conditions
  when you report.
- **Judge error** → aggregation drops error judges from the mean; proceed on a
  partial panel. If ALL judges errored for a build, report no score and offer to
  re-run those judge jobs.
- **Idempotency** → before launching a unit, skip it if its out_dir already has a
  `result.json` with `status:"complete"` (this is how resume reuses work). For an
  explicit retry, delete that unit's `result.json` (and its `worktree/`, plus
  `git worktree prune`) and relaunch only that session.

## Guardrails

- Always confirm the **job estimate** before launching:
  `unique_planners + len(conditions) + len(conditions)×len(judges)`, all × trials.
  (opus+kimi, 2 judges, 1 trial = 2 + 4 + 8 = 14 model-calling jobs.)
- Default 1 trial. Note that trials multiply every count above.
- Local-commit only; never push/PR. Judges run read-only.
- Report `cost_source` per condition; warn loudly when any model is off-registry
  (its dollar figure and efficiency are unreliable).
- **Cost accuracy / cache pricing (important for $/quality).** Only models whose
  provider returns billed cost show `cost_source: pi_reported`; the rest are
  `configured` (computed from `models.yaml` rates). An agentic implement loop is
  ~90% **cache-read** tokens, and if a `configured` model has no `cache_read`
  rate, `cost.py` charges cache hits at the **full input price** — inflating cost
  several-fold (Kimi looked ~4× too expensive until we set `cache_read: 0.16`).
  So: every `configured` model in `models.yaml` should have a `cache_read` (and,
  if known, `cache_write`) rate. If you can't get a real rate, say so — don't
  compare a `pi_reported` model against a `configured`-at-full-cache model and
  call it fair. (Already set: `kimi-k2.6 cache_read: 0.16`. `gpt-5.5` unset.)
  With rates in place, cost is correct at run time and no post-hoc recompute is
  needed.

## §8 Scaling to many issues/trials for statistical robustness (OPT-IN, EXPENSIVE)

**Do NOT do this by default.** The default is one issue, `--trials 1` — cheap and
fast. A single issue is an *anecdote*, not a scientific result, but multi-issue
sweeps cost real money (`issues × conditions × (planners + impl + judges) ×
trials` model jobs) and hit rate limits. Only run this when the user explicitly
asks to "make it scientific" / "run on multiple issues" / "average over runs",
and **confirm the full job count + rough cost first**.

**Two axes of replication (issues matter far more than trials):**
- **Trials per condition** (same issue) average out seed noise — LLMs vary even at
  temp 0. **3–5 trials** captures it; below 3 you can't estimate noise.
- **Distinct issues** drive generalizability and dominate the variance. Rough
  guide: **~10** issues = directional (enough for the big cost/efficiency gap),
  **~30** = defensible "scientific" (report per-condition means with 95% CIs),
  **50–100+** = strong/publishable. Tiny quality gaps (e.g. 7.5–8.5, within judge
  noise) may *never* separate — report that as the finding rather than chasing it.

**Design rules that make few issues go further:**
- **Paired/blocked:** run every condition on the *same* issue set, then compare
  *per-issue deltas* and **win-rates** ("Kimi beat Opus on $/quality on 27/30
  issues"), not just averaged means. duobench is naturally paired (all conditions
  share each issue) — exploit it; it sharply cuts the issues needed for power.
- **No selection bias:** sample a curated set across repos/difficulty (e.g. a
  SWE-bench Lite subset), don't hand-pick. (This is exactly what repo issue #5
  "benchmark-suite mode" is for.)

**Mechanics (no new engine code needed — reuse the per-unit flow):**
1. Run the full §4 pipeline **once per issue** into a sibling run dir, e.g.
   `runs/<ts>/issues/<owner>-<repo>-<num>/` (or one `runs/<ts>__<issue>/` each).
   For each issue from another repo, follow §1.5 (clone at its own pre-fix base).
   Condition ids are stable across issues, so they're the join key.
2. With `--trials N`, every phase job multiplies by N (`trial-0..N-1` dirs);
   `aggregate.py` already means-and-stds across a run's trials per condition.
3. **Cross-issue meta-aggregation** (small pandas step, not a model call): load
   each issue's `results.json`, group by `condition_id`, and average quality +
   cost across issues; also compute the paired win-rate per condition pair. Plot
   means with CI error bars (`cost_std`/`quality_std` × 1.96/√n) and a win-rate
   matrix. Keep per-issue `results.json` so nothing is lost.
4. Report it honestly: n (issues × trials), CIs, and which conclusions are robust
   (usually cost) vs within-noise (often quality).
