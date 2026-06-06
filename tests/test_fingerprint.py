from kcbench.config import Condition, Config, Model, Pricing
from kcbench.fingerprint import make_benchmark_fingerprint, sha256_text


def _cfg() -> Config:
    models = {
        "gpt-5.5": Model("gpt-5.5", "openai-codex", "gpt-5.5", Pricing(5, 30)),
        "kimi-k2.6": Model("kimi-k2.6", "kimi-coding", "kimi-for-coding", Pricing(0.95, 4)),
        "judge": Model("judge", "openai", "judge-model", Pricing(1, 2)),
    }
    return Config(models=models, judges=["judge"], conditions=[])


def test_fingerprint_is_stable_and_includes_prompt_hashes():
    cfg = _cfg()
    cond = Condition(id="gpt-x-kimi", planner="gpt-5.5", implementer="kimi-k2.6")
    prompts = {"architect": "plan this", "implement": "build this", "judge": "score this"}

    fp1 = make_benchmark_fingerprint(
        cfg, cond, prompts, dry_run=False, plan_timeout=600, impl_timeout=1800, judge_timeout=300
    )
    fp2 = make_benchmark_fingerprint(
        cfg, cond, prompts, dry_run=False, plan_timeout=600, impl_timeout=1800, judge_timeout=300
    )

    assert fp1.key == fp2.key
    assert fp1.label.startswith("webos-v1__gpt-5.5-x-kimi-k2.6__")
    assert fp1.payload["prompts"]["architect"] == sha256_text("plan this")
    assert fp1.payload["prompts"]["implement"] == sha256_text("build this")
    assert fp1.payload["prompts"]["judge"] == sha256_text("score this")


def test_prompt_content_change_changes_fingerprint_key():
    cfg = _cfg()
    cond = Condition(id="gpt-x-kimi", planner="gpt-5.5", implementer="kimi-k2.6")
    kwargs = dict(dry_run=False, plan_timeout=600, impl_timeout=1800, judge_timeout=300)

    before = make_benchmark_fingerprint(
        cfg, cond, {"architect": "plan this", "implement": "build this", "judge": "score this"}, **kwargs
    )
    after = make_benchmark_fingerprint(
        cfg, cond, {"architect": "plan this v2", "implement": "build this", "judge": "score this"}, **kwargs
    )

    assert before.key != after.key
