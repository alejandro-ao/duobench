# Prompt: run a MiniMax-M3 × kimi-for-coding duobench trial in tmux

Use this prompt with a coding agent on the server.

---

You are running a duobench benchmark while I am away. Please run it carefully in `tmux` and leave clear artifacts/logs.

## Goal

Benchmark these two Pi model specs on one GitHub issue from the local candidate list:

- `minimax/MiniMax-M3:high`
- `kimi-coding/kimi-for-coding:high`

Use these full `provider/model_id:thinking` specs exactly. Do not shorten them to bare model names — bare names skip duobench's registry defaults and run with thinking OFF, which changes the benchmark.

Use this issue/repo pair:

- Issue: https://github.com/generative-computing/mellea/issues/1219
- Fork to work from: https://github.com/alejandro-ao/mellea
- Candidate id: `mellea-1219`

This is an easy issue with an explicit one-line fix, useful as a first real workflow test.

## Important behavior

Duobench will create real branches and pull requests. Run only one trial, serially.

The judge panel is passed explicitly (`--judges kimi-k2.6,gpt-5.5`). Do not drop that flag: without it duobench defaults the judges to the competing models themselves, which biases scores.

Expected matrix size:

- 2 planner runs
- 4 implementer/PR attempts
- 2 judges × 4 PRs = 8 judge runs

## Steps

1. Make a working directory on the server:

```bash
mkdir -p ~/bench-runs
cd ~/bench-runs
```

2. Install or update duobench from the pushed GitHub repo:

```bash
uv tool install --force git+https://github.com/alejandro-ao/agent-synergy-eval.git@fix/dx-friction-round1
```

(The `fix/dx-friction-round1` branch carries the model-spec and cost-source fixes. If that branch is gone because the PR merged, install from `main` instead.)

3. Clone or update the fork repo:

```bash
cd ~/bench-runs
if [ ! -d mellea ]; then
  git clone git@github.com:alejandro-ao/mellea.git
fi
cd mellea
git fetch origin
if git remote get-url upstream >/dev/null 2>&1; then
  git fetch upstream
else
  git remote add upstream https://github.com/generative-computing/mellea.git
  git fetch upstream
fi
```

4. Confirm auth and model availability before starting the real run:

```bash
gh auth status
pi --list-models MiniMax-M3
pi --list-models kimi-for-coding
pi --model minimax/MiniMax-M3 -p "Reply with OK."
pi --model kimi-coding/kimi-for-coding -p "Reply with OK."
pi --model openai-codex/gpt-5.5 -p "Reply with OK."   # judge model
```

Each `--list-models` call must show the model under the expected provider (`minimax` / `kimi-coding`), and each `-p` call must reply OK (this also proves provider auth). If either exact model spec is unavailable, do **not** guess silently. Inspect `pi --list-models minimax` / `pi --list-models kimi`, choose the closest exact Pi model spec, and write down what changed in `~/bench-runs/duobench-model-resolution.txt`.

Cost note: neither spec has pricing in duobench's registry, so the leaderboard will show cost source `unknown` and cost `$0.0000` with a warning. That is expected for this run; quality scores are unaffected. Optionally create `~/bench-runs/mellea/costs.yaml` with real $/MTok rates from the provider pricing pages to get cost numbers:

```yaml
models:
  minimax/MiniMax-M3:high:
    input: <rate>
    output: <rate>
  kimi-coding/kimi-for-coding:high:
    input: 0.95
    output: 4.00
```

5. Run a cheap dry-run from inside the `mellea` repo:

```bash
duobench \
  --dry-run \
  --issue https://github.com/generative-computing/mellea/issues/1219 \
  --models minimax/MiniMax-M3:high,kimi-coding/kimi-for-coding:high \
  --judges kimi-k2.6,gpt-5.5 \
  --trials 1 \
  --parallel 1 \
  --no-live \
  --out ~/bench-runs/duobench-dry-runs
```

In the dry-run output, confirm the conditions list shows `thinking=high` for both models and that the only `*` unknown-model markers are for the two direct Pi specs (expected — they are not registry keys).

6. Start the real benchmark in tmux:

```bash
cd ~/bench-runs/mellea
mkdir -p ~/bench-runs/logs

tmux new-session -d -s duobench-minimax-kimi-mellea-1219 \
  'PYTHONUNBUFFERED=1 duobench \
    --issue https://github.com/generative-computing/mellea/issues/1219 \
    --models minimax/MiniMax-M3:high,kimi-coding/kimi-for-coding:high \
    --judges kimi-k2.6,gpt-5.5 \
    --trials 1 \
    --parallel 1 \
    --no-live \
    --plan-timeout 900 \
    --impl-timeout 2400 \
    --judge-timeout 600 \
    --out ~/bench-runs/duobench-runs \
    2>&1 | tee ~/bench-runs/logs/duobench-minimax-kimi-mellea-1219.log'
```

7. After starting it, report back only:

- tmux session name
- log path
- exact command running
- how to attach
- where the final report should appear

Useful monitoring commands:

```bash
tmux attach -t duobench-minimax-kimi-mellea-1219
tail -f ~/bench-runs/logs/duobench-minimax-kimi-mellea-1219.log
ls -lah ~/bench-runs/duobench-runs
```

## Do not

- Do not run more than one trial.
- Do not use `--parallel all`.
- Do not run additional issues.
- Do not delete generated PRs or branches.
- Do not change duobench code unless the dry-run fails due to a clear local setup issue; if that happens, stop and report the failure.
