"""Delegation economics: deep work stays in the main thread, small work runs inline, and the Codex
adapter spawns with explicit model + effort (named custom agents fail on multi-agent v2)."""
import copy
import re

import pytest

from openfusion import load_config
from openfusion.render import AGENTS_BLOCK_END, AGENTS_BLOCK_START, HARNESSES, install, render
from openfusion.router import Router, main_tier_for

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

CFG = load_config()
R = Router(CFG)
ARCH = "design the architecture for multi-tenant billing"
FEATURE = "add pagination to the users API"


@pytest.mark.parametrize("provider", list(CFG["providers"]))
def test_deep_stays_in_main_thread_by_default(provider):
    d = R.route(ARCH, provider=provider)
    assert d.tier == "deep" and d.main_tier == "deep" and d.run_in == "main"
    assert d.judge_in == "main"  # no critics on top of a deep main thread unless --effort max


def test_effort_max_still_gets_critics():
    d = R.route(ARCH, provider="codex", effort="max")
    assert d.run_in == "main" and d.judge_in == "worker"


def test_weaker_main_model_delegates_deep_work():
    d = R.route(ARCH, provider="codex", main_model="gpt-6.1-sol")
    assert d.main_tier == "standard" and d.run_in == "worker"
    d = R.route("debug the race condition in the job queue", provider="claude-code", main_model="sonnet")
    assert d.tier == "deep" and d.run_in == "worker"


def test_main_model_prefers_primary_tier():
    # gpt-6.1-sol is deep's fallback but standard's first choice -> standard.
    assert main_tier_for(CFG, "codex", main_model="gpt-6.1-sol", env={}) == "standard"
    assert main_tier_for(CFG, "codex", main_model="GPT-6-Astra", env={}) == "deep"
    assert main_tier_for(CFG, "codex", main_tier="fast", env={}) == "fast"
    assert main_tier_for(CFG, "codex", env={"OPENFUSION_MAIN_TIER": "standard"}) == "standard"
    with pytest.raises(ValueError):
        main_tier_for(CFG, "codex", main_tier="huge", env={})


def test_cascade_judge_on_main_tier_is_you():
    d = R.route(FEATURE, provider="codex")
    assert d.pattern == "cascade" and d.run_in == "worker" and d.judge_tier == "deep" and d.judge_in == "main"


def test_small_tasks_inline_bulk_tasks_delegate():
    assert R.route("fix typo in README", provider="codex").run_in == "main"
    assert R.route("just rename this variable", provider="codex").run_in == "main"
    assert R.route("find all usages of parse_date across the codebase", provider="codex").run_in == "worker"
    assert R.route("write unit tests for the parser module", provider="codex").run_in == "worker"


def test_bad_main_tier_in_config_rejected():
    cfg = copy.deepcopy(CFG)
    cfg["delegation"]["main_tier"]["codex"] = "huge"
    with pytest.raises(ValueError):
        Router(cfg)  # noqa: B018
        from openfusion.router import validate_config
        validate_config(cfg)


def test_codex_tier_efforts():
    p = CFG["providers"]["codex"]
    assert (p["fast"]["model"], p["fast"]["effort"]) == ("gpt-6-luna", "low")
    assert (p["standard"]["model"], p["standard"]["effort"]) == ("gpt-6.1-sol", "medium")


def test_codex_skill_spawns_explicitly(tmp_path):
    render("codex", CFG, tmp_path)
    skill = (tmp_path / ".agents/skills/openfusion/SKILL.md").read_text(encoding="utf-8")
    for needle in ("spawn_agent", "`model`", "`reasoning_effort`", 'fork_turns: "none"', "Don't pass `agent_type`",
                   "openai/codex#31893", "openai/codex#32831", "wait_agent", "timeout_ms",
                   "| `fusion_fast` | fast | `gpt-6-luna` | `low` |", "Never spawn a worker on your own model",
                   "At most 3 workers per task", "Batch, don't poll", "Deep = you", "Small = you"):
        assert needle in skill, needle
    agents_md = (tmp_path / "AGENTS.openfusion.md").read_text(encoding="utf-8")
    assert "never spawn a worker on your own model" in agents_md and "--main-model" in agents_md


@pytest.mark.parametrize("name", list(HARNESSES))
def test_every_skill_has_delegation_economics(name, tmp_path):
    render(name, CFG, tmp_path)
    skill = (tmp_path / HARNESSES[name].skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "## Delegation economics" in skill and "run_in" in skill and "{{" not in skill
    assert "**Normally you (main thread): don't spawn.**" in skill  # on the deep row


@pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")
def test_codex_config_snippet(tmp_path):
    render("codex", CFG, tmp_path)
    cfg = tomllib.loads((tmp_path / ".codex/config.openfusion.toml").read_text(encoding="utf-8"))
    assert cfg["agents"]["max_concurrent_threads_per_session"] == 3
    assert cfg["agents"]["default_subagent_model"] == "gpt-6-luna"
    assert cfg["agents"]["default_subagent_reasoning_effort"] == "low"
    assert cfg["features"]["multi_agent_v2"]["expose_spawn_agent_model_overrides"] is True


def test_codex_install_merges_agents_block(tmp_path):
    repo = tmp_path / "repo with space"
    repo.mkdir()
    install("codex", CFG, repo)
    text = (repo / ".codex/config.toml").read_text(encoding="utf-8")
    assert text.count(AGENTS_BLOCK_START) == 1 and not re.search(r"^model =", text, re.M)  # never sets the user's model
    (repo / ".codex/config.toml").write_text('model = "mine"\n\n' + text, encoding="utf-8")
    install("codex", CFG, repo)
    again = (repo / ".codex/config.toml").read_text(encoding="utf-8")
    assert again.startswith('model = "mine"') and again.count(AGENTS_BLOCK_END) == 1


def test_codex_install_leaves_existing_agents_table(tmp_path):
    repo = tmp_path / "r"
    (repo / ".codex").mkdir(parents=True)
    (repo / ".codex/config.toml").write_text("[agents]\nmax_threads = 9\n", encoding="utf-8")
    _, steps = install("codex", CFG, repo)
    assert (repo / ".codex/config.toml").read_text(encoding="utf-8") == "[agents]\nmax_threads = 9\n"
    assert any("by hand" in s for s in steps)


def test_antigravity_deep_inherits_and_avoids_self(tmp_path):
    render("antigravity", CFG, tmp_path)
    deep = (tmp_path / ".agents/agents/fusion-deep.md").read_text(encoding="utf-8")
    assert "model: inherit" in deep
    skill = (tmp_path / ".agents/skills/openfusion/SKILL.md").read_text(encoding="utf-8")
    assert "invoke_subagent" in skill and "`self`" in skill
