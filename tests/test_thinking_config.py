import io

from duobench.config import Config, Model, Pricing, load_config
from duobench.cost import PhaseCost
from duobench.pi_rpc import PiSession


class _FakeProc:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = iter(())
        self.stderr = iter(())

    def poll(self):
        return 0


def test_packaged_default_thinking_levels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.model("kimi-k2.6").thinking_level == "high"
    assert cfg.model("gpt-5.5").thinking_level == "off"


def test_pi_session_sends_rpc_set_thinking_level_command():
    session = PiSession(cwd=".")
    fake_proc = _FakeProc()
    fake_proc.poll = lambda: None
    session._proc = fake_proc
    session._events.put({"type": "response", "command": "set_thinking_level", "success": True})

    session.set_thinking("high")

    assert fake_proc.stdin.getvalue() == '{"type": "set_thinking_level", "level": "high"}\n'


def test_pi_session_persistence_controls_no_session_flag(monkeypatch, tmp_path):
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr("duobench.pi_rpc.subprocess.Popen", fake_popen)

    with PiSession(cwd=tmp_path, persist_session=True, session_name="duobench minidesk test"):
        pass

    assert "--no-session" not in captured["args"]
    assert captured["args"][:3] == ["pi", "--mode", "rpc"]
    assert captured["args"][3:5] == ["--name", "duobench minidesk test"]

    with PiSession(cwd=tmp_path, persist_session=False):
        pass

    assert "--no-session" in captured["args"]


def test_pi_session_prepends_extra_path(monkeypatch, tmp_path):
    captured = {}

    def fake_popen(args, **kwargs):
        captured["env"] = kwargs["env"]
        return _FakeProc()

    monkeypatch.setattr("duobench.pi_rpc.subprocess.Popen", fake_popen)

    extra = tmp_path / "bin"
    extra.mkdir()
    with PiSession(cwd=tmp_path, extra_path=extra):
        pass

    assert captured["env"]["PATH"].split(":")[0] == str(extra)


def test_plan_one_passes_configured_thinking_level_to_plan_phase(tmp_path, monkeypatch):
    import duobench.engine as engine_mod

    cfg = Config(
        models={"kimi": Model("kimi", "kimi-provider", "kimi-model", Pricing(1, 2), thinking_level="high")},
        judges=["kimi"],
        conditions=[],
    )
    captured = {}

    def fake_run_plan_phase(planner, architect_prompt, out_dir, **kwargs):
        captured["thinking_level"] = kwargs["thinking_level"]
        (out_dir / "plan.md").write_text("plan")
        return "plan", PhaseCost(1, 1, 0, 0, 0.01), 12.0

    monkeypatch.setattr(engine_mod, "run_plan_phase", fake_run_plan_phase)

    engine_mod.plan_one(
        cfg,
        {"architect": "prompt", "issue_url": "u"},
        "kimi",
        out_dir=tmp_path,
        trial=0,
        timeout=600,
    )

    assert captured["thinking_level"] == "high"
