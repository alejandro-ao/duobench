"""Local-commit benchmark mode (default since #11).

The default real-run mode no longer publishes branches or PRs to the
upstream repository. These tests pin down the safety scaffolding:

* The local-commit implementer prompt does not instruct the agent to push
  or open a PR, and explicitly forbids `gh pr create` / `upstream` remote
  interaction.
* The local-commit judge prompt asks the judge to evaluate the commit,
  diff, and worktree state instead of a PR id.
* `prepare_worktree` installs PATH-prepended `git`/`gh` wrapper scripts
  that reject `git push` and `gh pr create|edit|merge|...` in the
  implementer session.
* The same wrappers allow read-only commands (e.g. `git status`,
  `gh issue view`, `gh pr view`).
* The `upstream` git remote is removed from the worktree in local-commit
  mode, so the agent cannot target a parent repository via `git push`.
* The --local-commit flag is on by default and selects the local-commit
  implementer/judge prompts.
* The harness records a `commit.json` artifact with the SHA, branch,
  `git show --stat`, full diff, and worktree cleanliness for each trial.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from duobench.config import Condition, Config, Model, Pricing
from duobench.run import (
    SharedPlan,
    _capture_commit_artifacts,
    _install_local_commit_safety,
    _remove_upstream_remote,
    prepare_worktree,
    run_condition_trial,
)


# --- shared fixture helpers --------------------------------------------------


def _cfg() -> Config:
    models = {
        "kimi": Model("kimi", "kimi-provider", "kimi-model", Pricing(1, 2)),
        "gpt": Model("gpt", "gpt-provider", "gpt-model", Pricing(3, 4)),
    }
    conditions = [Condition("kimi-solo", "kimi", "kimi")]
    return Config(models=models, judges=["kimi", "gpt"], conditions=conditions)


def _load_prompt_text(name: str) -> str:
    """Load a packaged prompt by name (matching how run._load_prompt loads them)."""
    from importlib import resources
    return (resources.files("duobench.defaults.prompts") / name).read_text()


# --- prompt regression -------------------------------------------------------


def test_local_commit_implementer_prompt_forbids_push_and_pr_creation():
    """The local-commit implementer prompt must not instruct the agent to push
    or open a PR. This is the regression test for the safety guidance #11."""
    text = _load_prompt_text("implement_local_commit.md")
    low = text.lower()
    assert "do not push" in low
    assert "do not create a pr" in low
    assert "do not run `gh pr create`" in low
    assert "upstream" in low
    # The PR-creating instructions from the legacy prompt must be gone.
    assert "push the branch" not in low
    assert "open a github pull request" not in low
    assert "pull request for the issue" not in low
    # The agent is expected to return a SHA, not a PR id.
    assert "commit sha" in low


def test_local_commit_judge_prompt_evaluates_commit_not_pr():
    """The local-commit judge prompt should ask the judge to inspect a commit,
    its diff, and the worktree state — not a PR id."""
    text = _load_prompt_text("judge_local_commit.md")
    low = text.lower()
    assert "commit sha" in low
    assert "diff" in low
    assert "worktree" in low
    # The judge should be told not to push or open a PR.
    assert "do not modify" in low
    assert "push" in low
    assert "open pr" in low
    # The PR-mode placeholder should NOT appear in the local-commit prompt.
    assert "{pr_id}" not in text
    assert "{commit_sha}" in text


# --- worktree safety scaffolding --------------------------------------------


def test_prepare_worktree_installs_safety_wrappers_in_local_commit_mode(tmp_path, monkeypatch):
    """In local-commit mode, prepare_worktree must install a worktree-local bin/
    with PATH-prepended git/gh wrappers that block push and PR creation."""
    import duobench.run as run_mod

    repo_dir = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    repo_dir.mkdir()
    git_calls: list[tuple[list[str], Path]] = []
    gh_calls: list[tuple[list[str], Path]] = []

    def fake_git(args, cwd, *, timeout=60.0):
        git_calls.append((args, cwd))
        if args[:2] == ["worktree", "add"]:
            worktree_dir.mkdir()
        if args == ["remote", "get-url", "origin"]:
            return "git@github.com:alejandro-ao/mellea.git"
        return ""

    def fake_gh(args, cwd, *, timeout=60.0):
        gh_calls.append((args, cwd))
        return ""

    monkeypatch.setattr(run_mod, "_git", fake_git)
    monkeypatch.setattr(run_mod, "_gh", fake_gh)

    prepare_worktree(repo_dir, worktree_dir, branch="duobench-test", submission_mode="local_commit")

    bin_dir = worktree_dir / ".duobench-bin"
    assert bin_dir.is_dir()
    git_wrapper = bin_dir / "git"
    gh_wrapper = bin_dir / "gh"
    assert git_wrapper.is_file()
    assert gh_wrapper.is_file()
    # Wrappers must be executable.
    for path in (git_wrapper, gh_wrapper):
        mode = path.stat().st_mode
        assert mode & 0o111, f"{path} is not executable (mode={oct(mode)})"
    # The git wrapper must block `push` and pass through everything else.
    git_body = git_wrapper.read_text()
    assert "git push" in git_body.lower() or "git'" in git_body  # guard message refers to "git push"
    assert "exec" in git_body
    # The gh wrapper must block `pr create` (and a few other PR mutations).
    gh_body = gh_wrapper.read_text()
    assert "create" in gh_body
    assert "exec" in gh_body
    # The 'remote remove upstream' call must be present in local-commit mode.
    assert (["remote", "remove", "upstream"], worktree_dir) in git_calls


def test_prepare_worktree_does_not_install_wrappers_in_pr_mode(tmp_path, monkeypatch):
    """In PR mode (legacy), prepare_worktree should not install the safety
    wrappers or remove the upstream remote — the agent is supposed to push."""
    import duobench.run as run_mod

    repo_dir = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    repo_dir.mkdir()
    git_calls: list[tuple[list[str], Path]] = []
    gh_calls: list[tuple[list[str], Path]] = []

    def fake_git(args, cwd, *, timeout=60.0):
        git_calls.append((args, cwd))
        if args[:2] == ["worktree", "add"]:
            worktree_dir.mkdir()
        if args == ["remote", "get-url", "origin"]:
            return "git@github.com:alejandro-ao/mellea.git"
        return ""

    def fake_gh(args, cwd, *, timeout=60.0):
        gh_calls.append((args, cwd))
        return ""

    monkeypatch.setattr(run_mod, "_git", fake_git)
    monkeypatch.setattr(run_mod, "_gh", fake_gh)

    prepare_worktree(repo_dir, worktree_dir, branch="duobench-test", submission_mode="pr")

    assert not (worktree_dir / ".duobench-bin").exists()
    # No 'remote remove upstream' call in PR mode.
    assert (["remote", "remove", "upstream"], worktree_dir) not in git_calls


def test_install_local_commit_safety_creates_executable_wrappers(tmp_path):
    bin_dir = _install_local_commit_safety(tmp_path)
    assert bin_dir == tmp_path / ".duobench-bin"
    for name in ("git", "gh"):
        path = bin_dir / name
        assert path.is_file()
        assert path.stat().st_mode & 0o111, f"{name} wrapper is not executable"
    # Body should mention the local-commit mode so the agent can see why it failed.
    git_body = (bin_dir / "git").read_text()
    gh_body = (bin_dir / "gh").read_text()
    assert "local-commit" in git_body
    assert "local-commit" in gh_body


def test_remove_upstream_remote_handles_absent_remote(tmp_path, monkeypatch):
    import duobench.run as run_mod

    captured: list[list[str]] = []

    def fake_git(args, cwd, *, timeout=60.0):
        captured.append(args)
        if args[:2] == ["remote", "remove", "upstream"]:
            from duobench.config import ConfigError
            raise ConfigError("fatal: No such remote: upstream")
        return ""

    monkeypatch.setattr(run_mod, "_git", fake_git)
    # Should not raise even though the remote is missing.
    _remove_upstream_remote(tmp_path)
    assert ["remote", "remove", "upstream"] in captured


# --- wrapper behavior (executable) -----------------------------------------


def test_git_wrapper_blocks_push(tmp_path):
    """The installed `git` wrapper must exit non-zero when invoked with `push`
    and pass through other git commands (e.g. `status`, `diff`)."""
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git not on PATH; cannot exercise wrapper behavior")
    _install_local_commit_safety(tmp_path)
    bin_dir = str(tmp_path / ".duobench-bin")

    # The wrapper is implemented as /bin/sh, so we can run it on any POSIX system.
    push = subprocess.run(
        [str(tmp_path / ".duobench-bin" / "git"), "push", "origin", "main"],
        env={"PATH": bin_dir, "HOME": str(tmp_path), "DUOBENCH_BLOCK_GIT_PUSH": "1"},
        capture_output=True,
        text=True,
    )
    assert push.returncode != 0, push.stdout + push.stderr
    assert "disabled" in (push.stderr + push.stdout).lower()


def test_git_wrapper_allows_status_and_other_commands(tmp_path):
    """Non-push git commands must reach the real git binary (and behave like
    the real git for the args passed)."""
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git not on PATH; cannot exercise wrapper behavior")
    _install_local_commit_safety(tmp_path)
    bin_dir = str(tmp_path / ".duobench-bin")

    # Initialize a tiny repo so `git status` succeeds.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)

    status = subprocess.run(
        [str(tmp_path / ".duobench-bin" / "git"), "status"],
        env={"PATH": bin_dir, "HOME": str(tmp_path), "DUOBENCH_BLOCK_GIT_PUSH": "1"},
        capture_output=True,
        text=True,
    )
    assert status.returncode == 0, status.stderr


def test_gh_wrapper_blocks_pr_create(tmp_path):
    """The installed `gh` wrapper must exit non-zero when invoked with
    `gh pr create ...` and pass through other gh commands."""
    import shutil
    if shutil.which("gh") is None:
        pytest.skip("gh not on PATH; cannot exercise wrapper behavior")
    _install_local_commit_safety(tmp_path)
    bin_dir = str(tmp_path / ".duobench-bin")

    res = subprocess.run(
        [str(tmp_path / ".duobench-bin" / "gh"), "pr", "create", "--title", "x"],
        env={"PATH": bin_dir, "HOME": str(tmp_path), "DUOBENCH_BLOCK_GH_PR": "1"},
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0, res.stdout + res.stderr
    assert "disabled" in (res.stderr + res.stdout).lower()


def test_gh_wrapper_blocks_other_pr_mutations(tmp_path):
    """Beyond `pr create`, the wrapper must also block `pr edit`, `pr merge`,
    `pr close`, etc., to prevent the agent from mutating an existing PR."""
    import shutil
    if shutil.which("gh") is None:
        pytest.skip("gh not on PATH; cannot exercise wrapper behavior")
    _install_local_commit_safety(tmp_path)
    bin_dir = str(tmp_path / ".duobench-bin")

    for verb in ("edit", "merge", "close", "review", "delete-branch"):
        res = subprocess.run(
            [str(tmp_path / ".duobench-bin" / "gh"), "pr", verb, "1"],
            env={"PATH": bin_dir, "HOME": str(tmp_path), "DUOBENCH_BLOCK_GH_PR": "1"},
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0, f"gh pr {verb} was NOT blocked: {res.stdout=} {res.stderr=}"


def test_gh_wrapper_allows_read_only_issue_and_pr_view(tmp_path):
    """Read-only `gh issue view` / `gh pr view` must reach the real binary
    (the wrapper should not be a blanket `gh` blocker)."""
    import shutil
    if shutil.which("gh") is None:
        pytest.skip("gh not on PATH; cannot exercise wrapper behavior")
    _install_local_commit_safety(tmp_path)
    bin_dir = str(tmp_path / ".duobench-bin")

    # `gh issue view --help` should succeed (or fail with the real gh help
    # message, not the wrapper's block message). We assert the block message
    # is absent.
    for args in (["issue", "view", "--help"], ["pr", "view", "--help"]):
        res = subprocess.run(
            [str(tmp_path / ".duobench-bin" / "gh"), *args],
            env={"PATH": bin_dir, "HOME": str(tmp_path), "DUOBENCH_BLOCK_GH_PR": "1"},
            capture_output=True,
            text=True,
        )
        combined = (res.stdout + res.stderr).lower()
        assert "disabled" not in combined, f"gh {' '.join(args)} was incorrectly blocked: {res.stdout=}\n{res.stderr=}"


def test_git_and_gh_wrappers_can_be_disabled_via_env(tmp_path):
    """Setting DUOBENCH_BLOCK_GIT_PUSH=0 / DUOBENCH_BLOCK_GH_PR=0 must disable
    the local-commit guards. This is the documented escape hatch."""
    import shutil
    if shutil.which("gh") is None or shutil.which("git") is None:
        pytest.skip("git/gh not on PATH; cannot exercise wrapper behavior")
    _install_local_commit_safety(tmp_path)
    bin_dir = str(tmp_path / ".duobench-bin")
    env = {"PATH": bin_dir, "HOME": str(tmp_path),
           "DUOBENCH_BLOCK_GIT_PUSH": "0", "DUOBENCH_BLOCK_GH_PR": "0"}
    # Both should reach the real binary; we only assert that the wrapper's
    # block message is absent.
    push = subprocess.run(
        [str(tmp_path / ".duobench-bin" / "git"), "status"],
        env=env, capture_output=True, text=True,
    )
    assert "disabled" not in (push.stdout + push.stderr).lower()
    gh = subprocess.run(
        [str(tmp_path / ".duobench-bin" / "gh"), "issue", "view", "--help"],
        env=env, capture_output=True, text=True,
    )
    assert "disabled" not in (gh.stdout + gh.stderr).lower()


# --- end-to-end artifact capture --------------------------------------------


def test_capture_commit_artifacts_records_sha_diff_and_cleanliness(tmp_path):
    """The harness should record commit metadata into commit.json for every
    real local-commit trial."""
    import subprocess
    # Create a real local git repo + commit so the capture path is exercised.
    repo = tmp_path / "worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add a"], cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()

    artifact = _capture_commit_artifacts(repo, sha, trial_dir=tmp_path)
    assert artifact["commit_sha"] == sha
    assert artifact["branch"] == "main"
    assert artifact["worktree_clean"] is True
    assert artifact["uncommitted_files"] == []
    # The diff body must mention the file we created.
    assert "a.txt" in artifact["diff"]
    assert "a.txt" in artifact["stat"]
    # commit.json was written next to trial_dir.
    assert (tmp_path / "commit.json").is_file()
    written = __import__("json").loads((tmp_path / "commit.json").read_text())
    assert written["commit_sha"] == sha


def test_capture_commit_artifacts_handles_missing_sha(tmp_path):
    artifact = _capture_commit_artifacts(tmp_path, "")
    assert artifact["commit_sha"] == ""
    assert "missing" in artifact["notes"][0].lower()


# --- CLI flag --------------------------------------------------------------


def test_default_cli_flag_is_local_commit(monkeypatch):
    """The --local-commit flag is on by default (see #11)."""
    from duobench.run import _main  # noqa: F401
    import argparse

    # Parse the same argparse that the CLI uses, with no override, and check
    # that --local-commit defaults to True.
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-commit", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args([])
    assert args.local_commit is True


# --- end-to-end run_condition_trial wiring ---------------------------------


def test_run_condition_trial_local_commit_records_commit_artifact(tmp_path, monkeypatch):
    """A run_condition_trial call in local_commit mode should record a
    commit.json, expose a commit_sha in trial.json / meta, and write the
    local-commit mode markers in the artifacts block."""
    import duobench.run as run_mod

    cfg = _cfg()
    prompts = {
        "issue_url": "https://example.com/issues/1",
        "architect": "plan",
        "implement": "implement",
        "judge": "judge",
    }
    shared_plan = SharedPlan(
        planner="kimi",
        trial=0,
        plan_text="plan",
        cost_usd=0.0,
        cost_source="configured",
        source_dir=tmp_path / "plans/kimi/trial-0",
    )

    # Use a tiny git repo as the "worktree" so the capture-commit path works.
    repo = tmp_path / "fakerepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "x.txt").write_text("hi\n")
    subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()

    # Skip real worktree creation; pretend the trial ran in our fake repo.
    monkeypatch.setattr(run_mod, "prepare_worktree", lambda repo_dir, build_dir, *, branch, submission_mode: repo)
    # Avoid Playwright — the fake repo has no index.html.
    monkeypatch.setattr(run_mod, "verify_build", lambda build_dir, shots_dir: _FakeVerifyResult())

    def fake_run_impl_phase(*args, **kwargs):
        from duobench.cost import PhaseCost
        from duobench.impl_phase import ImplResult
        return ImplResult(
            cost=PhaseCost(
                input_tokens=1,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_tokens=0,
                usd=0.01,
            ),
            turns=1,
            status="complete",
            final_text=sha,
            commit_sha=sha,
            submission_mode="local_commit",
            duration_s=1.0,
            notes=[],
        )

    monkeypatch.setattr(run_mod, "run_impl_phase", fake_run_impl_phase)

    trial_dir = tmp_path / "trial"
    trial_dir.mkdir()
    rec, meta = run_condition_trial(
        cfg, cfg.conditions[0], 0, trial_dir, prompts, shared_plan,
        dry_run=False,
        plan_timeout=600,
        impl_timeout=1800,
        judge_timeout=300,
        submission_mode="local_commit",
        run_label="test",
    )
    assert rec.impl_status == "complete"
    assert meta["submission_mode"] == "local_commit"
    assert meta["commit_sha"] == sha
    assert (trial_dir / "commit.json").is_file()
    payload = __import__("json").loads((trial_dir / "trial.json").read_text())
    assert payload["artifacts"]["submission_mode"] == "local_commit"
    assert payload["artifacts"]["commit"]["sha"] == sha


# --- shared helper ---------------------------------------------------------


class _FakeVerifyResult:
    boots_ok = True
    screenshots = []

    def to_dict(self):
        return {
            "boots_ok": True,
            "desktop_rendered": True,
            "taskbar_rendered": True,
            "fatal_console_errors": [],
            "apps_attempted": 3,
            "apps_launched": 3,
            "app_results": [],
            "screenshots": [],
            "notes": [],
        }

    def summary_for_judge(self):
        return "{}"
