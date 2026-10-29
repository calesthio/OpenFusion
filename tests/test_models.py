"""Model candidates, fallback and overrides (providers.<harness>.<tier>.candidates)."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from openfusion import load_config, normalize_providers, resolve_model
from openfusion.cli import main, parse_available
from openfusion.render import HARNESSES, install, render
from openfusion.router import Router, env_override_names, validate_config

CFG = load_config()
LADDER = CFG["escalation_ladder"]


def front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text[4:].split("\n---\n", 1)[0])


@pytest.fixture
def cfg():
    c = copy.deepcopy(CFG)
    c["providers"]["cursor"]["deep"] = {"candidates": ["a-model", "b-model", "c-model"], "effort": "high"}
    return c


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo ü"
    d.mkdir()
    return d


def test_every_tier_normalized_with_candidates():
    for prov, mapping in CFG["providers"].items():
        for t in LADDER:
            e = mapping[t]
            assert e["candidates"] and e["model"] == e["candidates"][0], (prov, t)


@pytest.mark.parametrize("entry,expected", [
    ("solo", ["solo"]),
    (["x", "y"], ["x", "y"]),
    ({"model": "x"}, ["x"]),
    ({"model": ["x", "y"]}, ["x", "y"]),
    ({"candidates": ["x", "y"], "model": "ignored"}, ["x", "y"]),
])
def test_normalize_accepts_all_shapes(entry, expected):
    c = {"providers": {"p": {"fast": entry}}}
    normalize_providers(c)
    normalize_providers(c)  # idempotent
    assert c["providers"]["p"]["fast"]["candidates"] == expected
    assert c["providers"]["p"]["fast"]["model"] == expected[0]


def test_normalize_rejects_empty():
    with pytest.raises(ValueError):
        normalize_providers({"providers": {"p": {"fast": {"candidates": []}}}})


def test_validate_config_normalizes_raw_dicts(cfg):
    cfg["providers"]["codex"]["fast"] = "gpt-x"
    validate_config(cfg)
    assert cfg["providers"]["codex"]["fast"] == {"model": "gpt-x", "candidates": ["gpt-x"]}


def test_resolve_first_candidate_by_default(cfg):
    m = resolve_model(cfg, "cursor", "deep", env={})
    assert m["model"] == "a-model" and m["source"] == "candidate" and m["effort"] == "high"


def test_resolve_falls_back_to_first_available(cfg):
    m = resolve_model(cfg, "cursor", "deep", available=["C-MODEL", "b-model"], env={})
    assert m["model"] == "b-model" and m["source"] == "fallback"


def test_resolve_skip_moves_down_the_list(cfg):
    assert resolve_model(cfg, "cursor", "deep", skip=["a-model"], env={})["model"] == "b-model"
    assert resolve_model(cfg, "cursor", "deep", skip=["a-model", "b-model"], env={})["model"] == "c-model"


def test_resolve_none_available(cfg):
    m = resolve_model(cfg, "cursor", "deep", available=["other"], env={})
    assert m["model"] is None and m["source"] == "none"


def test_env_override_specific_beats_generic(cfg):
    specific, generic = env_override_names("cursor", "deep")
    assert (specific, generic) == ("OPENFUSION_MODEL_CURSOR_DEEP", "OPENFUSION_MODEL_DEEP")
    assert env_override_names("github-copilot", "fast")[0] == "OPENFUSION_MODEL_GITHUB_COPILOT_FAST"
    m = resolve_model(cfg, "cursor", "deep", available=[], env={generic: "g", specific: "s"})
    assert m["model"] == "s" and m["source"] == "env" and m["override"] == specific
    assert resolve_model(cfg, "cursor", "deep", env={generic: "g"})["model"] == "g"
    assert resolve_model(cfg, "cursor", "deep", env={specific: "  "})["model"] == "a-model"


def test_resolve_unknown_provider_or_tier(cfg):
    with pytest.raises(ValueError):
        resolve_model(cfg, "nope", "deep", env={})
    with pytest.raises(ValueError):
        resolve_model(cfg, "cursor", "ultra", env={})


def test_router_uses_env_override(monkeypatch):
    monkeypatch.setenv("OPENFUSION_MODEL_CLAUDE_CODE_DEEP", "claude-opus-5-5")
    d = Router(CFG).route("fix the flaky race condition in the job queue", provider="claude-code")
    assert d.tier == "deep" and d.model["model"] == "claude-opus-5-5"


def test_copilot_writes_ordered_list(repo):
    render("github-copilot", CFG, repo)
    m = front(repo / ".github/agents/fusion-deep.agent.md")
    assert m["model"] == CFG["providers"]["github-copilot"]["deep"]["candidates"]
    assert isinstance(m["model"], list) and len(m["model"]) > 1


def test_copilot_available_filters_list(repo):
    render("github-copilot", CFG, repo, available=["GPT-6 Astra (copilot)", "Claude Sonnet 5.5 (copilot)"])
    m = front(repo / ".github/agents/fusion-deep.agent.md")
    assert m["model"] == ["GPT-6 Astra (copilot)", "Claude Sonnet 5.5 (copilot)"]


def test_copilot_nothing_available_omits_model(repo):
    render("github-copilot", CFG, repo, available=["nothing"])
    assert "model" not in front(repo / ".github/agents/fusion-fast.agent.md")


@pytest.mark.parametrize("name,path,inherit", [
    ("claude-code", ".claude/agents/fusion-deep.md", "inherit"),
    ("cursor", ".cursor/agents/fusion-deep.md", "inherit"),
    ("gemini-cli", ".gemini/agents/fusion-deep.md", "inherit"),
    ("antigravity", ".agents/agents/fusion-deep.md", "inherit"),
    ("opencode", ".opencode/agents/fusion-deep.md", None),
])
def test_no_available_candidate_inherits(name, path, inherit, repo):
    render(name, CFG, repo, available=["nothing"])
    assert front(repo / path).get("model") == inherit


def test_codex_no_available_candidate_omits_model(repo):
    render("codex", CFG, repo, available=["nothing"])
    text = (repo / ".codex/agents/fusion_deep.toml").read_text(encoding="utf-8")
    assert "\nmodel =" not in text and "inherits from parent" in text


def test_install_available_picks_fallback(repo):
    paths, steps = install("cursor", CFG, repo, available=["composer-2.5", "gpt-5.6-sol"], env={})
    assert front(repo / ".cursor/agents/fusion-fast.md")["model"] == "composer-2.5"
    assert front(repo / ".cursor/agents/fusion-standard.md")["model"] == "gpt-5.6-sol"
    assert front(repo / ".cursor/agents/fusion-deep.md")["model"] == "gpt-5.6-sol"
    assert any("fallback gpt-5.6-sol" in s for s in steps)
    skill = (repo / ".cursor/skills/openfusion/SKILL.md").read_text(encoding="utf-8")
    assert "`gpt-5.6-sol`" in skill


def test_install_env_override(repo):
    _, steps = install("claude-code", CFG, repo, env={"OPENFUSION_MODEL_CLAUDE_CODE_DEEP": "claude-opus-5-5"})
    assert front(repo / ".claude/agents/fusion-deep.md")["model"] == "claude-opus-5-5"
    assert front(repo / ".claude/agents/fusion-fast.md")["model"] == "haiku"
    assert any("OPENFUSION_MODEL_CLAUDE_CODE_DEEP" in s for s in steps)


def test_render_ignores_process_env(monkeypatch, repo):
    """Checked-in adapters must not depend on the developer's environment."""
    monkeypatch.setenv("OPENFUSION_MODEL_DEEP", "leaked")
    render("claude-code", CFG, repo)
    assert front(repo / ".claude/agents/fusion-deep.md")["model"] == "opus"


def test_skill_table_lists_fallbacks(repo):
    render("opencode", CFG, repo)
    skill = (repo / ".opencode/skills/openfusion/SKILL.md").read_text(encoding="utf-8")
    assert "Fallbacks (in order)" in skill and "`openai/gpt-6-astra`" in skill
    assert "resolve <tier> --skip" in skill


def test_parse_available(tmp_path):
    f = tmp_path / "models.txt"
    f.write_text("# comment\nanthropic/claude-opus-5-5\n\nopenai/gpt-6-astra\n", encoding="utf-8")
    assert parse_available(None) is None
    assert parse_available(["a, b", f"@{f}"]) == ["a", "b", "anthropic/claude-opus-5-5", "openai/gpt-6-astra"]
    cmd = f'"{sys.executable}" -c "print(\'x/one\'); print(\'y/two\')"'
    assert parse_available(None, cmd) == ["x/one", "y/two"]


def test_cli_resolve(capsys):
    assert main(["resolve", "deep", "--provider", "opencode", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["model"] == "anthropic/claude-opus-5-5"
    assert main(["resolve", "deep", "--provider", "opencode", "--skip", "anthropic/claude-opus-5-5"]) == 0
    assert "openai/gpt-6-astra [fallback]" in capsys.readouterr().out
    assert main(["resolve", "--provider", "opencode", "--available", "openai/gpt-6-luna"]) == 1
    out = capsys.readouterr().out
    assert "fast: openai/gpt-6-luna [fallback]" in out and "inherit" in out
    with pytest.raises(SystemExit):
        main(["resolve", "deep"])  # no provider in the checkout config


def test_bundled_route_py_resolve(repo):
    render("github-copilot", CFG, repo)
    script = repo / ".github/skills/openfusion/scripts/route.py"
    out = subprocess.run([sys.executable, str(script), "resolve", "deep", "--skip", "Claude Opus 5.5 (copilot)"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "deep: GPT-6 Astra (copilot) [fallback]"


@pytest.mark.parametrize("name", [h for h in HARNESSES if h != "generic"])
def test_last_resort_is_real_model(name):
    """No placeholder strings anywhere in real harness candidate lists."""
    for t in LADDER:
        assert all(not c.startswith("<") for c in CFG["providers"][name][t]["candidates"])
