# Prompt: run a MiniMax-M3 × kimi-for-coding duobench trial in tmux

Use this prompt with a coding agent on the server.

---

You are running a duobench benchmark while I am away. Please run it carefully in `tmux` and leave clear artifacts/logs.

## Goal

Benchmark these two Pi model specs on one GitHub issue from the local candidate list:

- `MiniMax-M3`
- `kimi-for-coding`

Use this issue/repo pair:

- Issue: https://github.com/generative-computing/mellea/issues/1219
- Fork to work from: https://github.com/alejandro-ao/mellea
- Candidate id: `mellea-1219`

This is an easy issue with an explicit one-line fix, useful as a first real workflow test.

## Important behavior

Duobench will create real branches and pull requests. Run only one trial, serially.

Expected matrix size:

- 2 planner runs
- 4 implementer/PR attempts
- judge panel over every PR

## Steps

1. Make a working directory on the server:

```bash
mkdir -p ~/bench-runs
cd ~/bench-runs
```

2. Install or update duobench from the pushed GitHub repo:

```bash
uv tool install --force git+https://github.com/alejandro-ao/agent-synergy-eval.git
```

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
pi --list-models MiniMax-M3 || true
pi --list-models kimi-for-coding || true
```

If either exact model spec is unavailable, do **not** guess silently. Inspect `pi --list-models minimax` / `pi --list-models kimi`, choose the closest exact Pi model spec, and write down what changed in `~/bench-runs/duobench-model-resolution.txt`.

5. Run a cheap dry-run from inside the `mellea` repo:

```bash
duobench \
  --dry-run \
  --issue https://github.com/generative-computing/mellea/issues/1219 \
  --models MiniMax-M3,kimi-for-coding \
  --trials 1 \
  --parallel 1 \
  --no-live \
  --out ~/bench-runs/duobench-dry-runs
```

6. Start the real benchmark in tmux:

```bash
cd ~/bench-runs/mellea
mkdir -p ~/bench-runs/logs

tmux new-session -d -s duobench-minimax-kimi-mellea-1219 \
  'PYTHONUNBUFFERED=1 duobench \
    --issue https://github.com/generative-computing/mellea/issues/1219 \
    --models MiniMax-M3,kimi-for-coding \
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
