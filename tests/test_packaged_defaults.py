from duobench.config import load_config
from duobench.run import _load_prompt


def test_load_config_falls_back_to_packaged_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert "gpt-5.5" in cfg.models
    assert any(c.id == "gpt-x-kimi" for c in cfg.conditions)


def test_load_prompt_falls_back_to_packaged_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    prompt = _load_prompt("architect.md")

    assert "MiniDesk" in prompt
