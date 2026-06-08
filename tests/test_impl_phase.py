from duobench.config import Model, Pricing
from duobench.impl_phase import _detect_existing_pr_id, extract_commit_sha, run_impl_phase
from duobench.pi_rpc import PiRpcStalled, TurnResult, Usage


def _model() -> Model:
    return Model("impl", "", "impl-model", Pricing(input=1.0, output=1.0))


class _FakeSession:
    def __init__(self, cwd, **kwargs):
        self.prompt_results = list(type(self).prompt_results)
        self.follow_up_results = list(type(self).follow_up_results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def prompt(self, message, *, timeout, idle_timeout=None):
        result = self.prompt_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def follow_up(self, message, *, timeout, idle_timeout=None):
        result = self.follow_up_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get_state(self):
        return {}


def test_impl_phase_retries_stalled_follow_up_as_prompt(tmp_path, monkeypatch):
    import duobench.impl_phase as impl_mod

    _FakeSession.prompt_results = [
        TurnResult("", Usage(output=3)),
        TurnResult("https://github.com/alejandro-ao/mellea/pull/123", Usage(output=9)),
    ]
    _FakeSession.follow_up_results = [PiRpcStalled("no agent_start after queued turn")]
    monkeypatch.setattr(impl_mod, "PiSession", _FakeSession)

    result = run_impl_phase(
        _model(), "{plan}", "plan", tmp_path / "build", timeout=30, submission_mode="pr"
    )

    assert result.status == "complete"
    assert result.pr_id == "123"
    assert result.turns == 2
    assert "retrying as fresh prompt" in result.notes[0]


def test_impl_phase_records_stalled_status_after_retry_stalls(tmp_path, monkeypatch):
    import duobench.impl_phase as impl_mod

    _FakeSession.prompt_results = [
        TurnResult("", Usage(output=3)),
        PiRpcStalled("no RPC events"),
    ]
    _FakeSession.follow_up_results = [PiRpcStalled("no agent_start after queued turn")]
    monkeypatch.setattr(impl_mod, "PiSession", _FakeSession)

    result = run_impl_phase(
        _model(), "{plan}", "plan", tmp_path / "build", timeout=30, submission_mode="pr"
    )

    assert result.status == "stalled"
    assert result.turns == 1
    assert any("fresh prompt after stalled follow-up also stalled" in note for note in result.notes)


def test_detect_existing_pr_id_reads_current_branch_pr(tmp_path, monkeypatch):
    import duobench.impl_phase as impl_mod

    calls = []

    class Result:
        def __init__(self, returncode=0, stdout=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["git", "branch", "--show-current"]:
            return Result(stdout="fix-empty-final\n")
        if args[:3] == ["gh", "pr", "list"]:
            return Result(stdout='[{"number": 456, "url": "https://github.com/a/b/pull/456"}]')
        raise AssertionError(args)

    monkeypatch.setattr(impl_mod.subprocess, "run", fake_run)

    assert _detect_existing_pr_id(tmp_path) == "456"
    assert calls[1] == [
        "gh",
        "pr",
        "list",
        "--head",
        "fix-empty-final",
        "--json",
        "number,url",
        "--limit",
        "1",
    ]


def test_extract_commit_sha_ignores_plain_completion_words():
    assert extract_commit_sha("committed") == ""
    assert extract_commit_sha("created commit") == ""
    assert extract_commit_sha("commit 1234567") == "1234567"


def test_impl_phase_infers_new_head_when_agent_says_committed(tmp_path, monkeypatch):
    import subprocess
    import duobench.impl_phase as impl_mod

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)

    class CommitSession(_FakeSession):
        def prompt(self, message, *, timeout, idle_timeout=None):
            (repo / "change.txt").write_text("change\n")
            subprocess.run(["git", "add", "change.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=repo, check=True)
            return TurnResult("committed", Usage(output=3))

    CommitSession.prompt_results = []
    CommitSession.follow_up_results = []
    monkeypatch.setattr(impl_mod, "PiSession", CommitSession)

    result = run_impl_phase(_model(), "{plan}", "plan", repo, timeout=30)

    assert result.status == "complete"
    assert len(result.commit_sha) == 40
