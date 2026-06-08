from pathlib import Path

import pytest

from duobench.config import ConfigError
from duobench.engine import _origin_repo_slug, prepare_worktree


@pytest.mark.parametrize(
    ("remote_url", "repo"),
    [
        ("git@github.com:alejandro-ao/mellea.git", "alejandro-ao/mellea"),
        ("https://github.com/alejandro-ao/mellea.git", "alejandro-ao/mellea"),
        ("ssh://git@github.com/alejandro-ao/mellea.git", "alejandro-ao/mellea"),
    ],
)
def test_origin_repo_slug_accepts_github_remote_formats(remote_url, repo):
    assert _origin_repo_slug(remote_url) == repo


def test_origin_repo_slug_rejects_unknown_remote():
    with pytest.raises(ConfigError):
        _origin_repo_slug("https://example.com/alejandro-ao/mellea.git")


def test_prepare_worktree_sets_origin_default_and_push_guard(tmp_path, monkeypatch):
    import duobench.engine as run_mod

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

    prepare_worktree(repo_dir, worktree_dir, branch="duobench-test")

    assert gh_calls == [(["repo", "set-default", "alejandro-ao/mellea"], worktree_dir)]
    assert (["config", "--worktree", "core.hooksPath", ".git-hooks"], worktree_dir) in git_calls

    hook = worktree_dir / ".git-hooks" / "pre-push"
    assert hook.exists()
    assert hook.stat().st_mode & 0o111
    assert 'remote_name="$1"' in hook.read_text()
    assert '[ "$remote_name" != "origin" ]' in hook.read_text()
