"""Render/install tests for every harness. Path-agnostic: they use tmp folders with spaces and
non-ASCII names and only pathlib, so they run the same on Windows, macOS and Linux."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from openfusion import load_config
from openfusion.cli import main
from openfusion.render import HARNESSES, MARK_END, MARK_START, install, render, render_all, roles

CFG = load_config()
ROOT = Path(__file__).resolve().parents[1]
ROLE_NAMES = ["fast", "standard", "deep", "judge-standard", "judge-deep", "critic"]
REVIEWERS = {"judge-standard", "judge-deep", "critic"}
try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def front(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(head), body


def files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def role_tier(role):
    return {r.key: r.tier for r in roles(CFG)}[role]


@pytest.fixture
def weird(tmp_path):
    d = tmp_path / "my repo ü 项目"
    d.mkdir()
    return d


def test_roles_cover_tiers_and_judges():
    rs = {r.key: r for r in roles(CFG)}
    assert list(rs) == ROLE_NAMES
    assert rs["judge-standard"].tier == "standard" and rs["judge-deep"].tier == "deep"
    assert rs["critic"].tier == CFG["patterns"]["critique"]["critic_tier"]


@pytest.mark.parametrize("name", list(HARNESSES))
def test_render_harness(name, weird):
    h = HARNESSES[name]
    paths = render(name, CFG, weird)
    assert paths and all(p.exists() for p in paths)
    models = CFG["providers"][name]
    skill = weird / h.skill_dir / "SKILL.md"
    meta, body = front(skill)
    assert meta["name"] == "openfusion" and meta["description"]
    for role in ROLE_NAMES:
        agent = h.agent_name(role)
        assert f"`{agent}`" in body
    # every placeholder filled, everywhere
    for p in weird.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".mdc", ".toml", ".json", ".py"):
            assert "{{" not in p.read_text(encoding="utf-8"), p
    # per-harness agent files
    for role in ROLE_NAMES:
        model = models[role_tier(role)]["model"]
        reviewer = role in REVIEWERS
        agent = h.agent_name(role)
        if name == "claude-code":
            m, _ = front(weird / f".claude/agents/{agent}.md")
            assert m["name"] == agent and m["model"] == model
            assert ("tools" in m) == reviewer
        elif name == "codex":
            if tomllib is None:
                pytest.skip("tomllib needs Python 3.11+")
            d = tomllib.loads((weird / f".codex/agents/{agent}.toml").read_text(encoding="utf-8"))
            assert d["name"] == agent and d["model"] == model and d["developer_instructions"]
            assert d["model_reasoning_effort"] == models[role_tier(role)]["effort"]
        elif name == "cursor":
            m, _ = front(weird / f".cursor/agents/{agent}.md")
            assert m["name"] == agent and m["model"] == model
            assert m.get("readonly", False) == reviewer
        elif name == "github-copilot":
            m, _ = front(weird / f".github/agents/{agent}.agent.md")
            cands = models[role_tier(role)]["candidates"]
            assert m["name"] == agent and m["user-invocable"] is False
            assert m["model"] == (cands if len(cands) > 1 else cands[0])  # ordered list, first available wins
            assert ("edit" not in m.get("tools", [])) if reviewer else "tools" not in m
        elif name == "gemini-cli":
            m, b = front(weird / f".gemini/agents/{agent}.md")
            assert m["name"] == agent and m["model"] == model and m["kind"] == "local"
        elif name == "antigravity":
            m, _ = front(weird / f".agents/agents/{agent}.md")
            assert m["name"] == agent and m["model"] == model in ("flash", "pro", "inherit")
            assert m["subagent"] is True and m["mainAgent"] is False
            assert ("replace_file_content" not in m.get("tools", [])) if reviewer else "tools" not in m
        elif name == "opencode":
            m, _ = front(weird / f".opencode/agents/{agent}.md")
            assert m["mode"] == "subagent" and m["model"] == model
            assert (m.get("permission", {}).get("edit") == "deny") == reviewer
        elif name == "generic":
            assert (weird / h.skill_dir / "agents" / f"{agent}.md").exists()
    if name == "cursor":
        m, _ = front(weird / ".cursor/rules/openfusion.mdc")
        assert m["alwaysApply"] is True
    if name == "antigravity":
        m, b = front(weird / ".agents/rules/openfusion.md")
        assert m["trigger"] == "always_on" and "fusion-deep" in b
    if name == "github-copilot":
        m, b = front(weird / ".github/agents/openfusion.agent.md")
        assert m["name"] == "OpenFusion" and "fusion-deep" in b
    if name == "codex" and tomllib:
        for t in CFG["escalation_ladder"]:
            tomllib.loads((weird / f".codex/profiles/fusion-{t}.config.toml").read_text(encoding="utf-8"))
        tomllib.loads((weird / ".codex/config.openfusion.toml").read_text(encoding="utf-8"))


def test_codex_names_use_underscores(tmp_path):
    render("codex", CFG, tmp_path)
    body = (tmp_path / ".agents/skills/openfusion/SKILL.md").read_text(encoding="utf-8")
    assert "`fusion_deep`" in body and "`fusion-deep`" not in body


@pytest.mark.parametrize("name", list(HARNESSES))
def test_bundled_router_runs_without_pyyaml(name, weird):
    render(name, CFG, weird)
    route_py = weird / HARNESSES[name].skill_dir / "scripts" / "route.py"
    cfg = json.loads((route_py.parent / "openfusion.json").read_text(encoding="utf-8"))
    assert cfg["default_provider"] == name
    # -S: no site-packages, so PyYAML can't be imported; run from an unrelated cwd.
    out = subprocess.run([sys.executable, "-S", str(route_py), "--json", "rename foo to bar"],
                         capture_output=True, text=True, cwd=str(weird.parent), check=True).stdout
    d = json.loads(out)
    assert d["tier"] == "fast" and d["model"]["model"] == CFG["providers"][name]["fast"]["model"]
    v = subprocess.run([sys.executable, "-S", str(route_py), "judge"], input="not json",
                       capture_output=True, text=True)
    assert v.returncode == 2 and json.loads(v.stdout)["assessment"] == "revise"


@pytest.mark.parametrize("name", list(HARNESSES))
def test_render_is_deterministic_and_lf_only(name, tmp_path):
    a, b = tmp_path / "a dir", tmp_path / "b ü"
    render(name, CFG, a)
    render(name, CFG, b)
    fa, fb = files(a), files(b)
    assert fa == fb  # no absolute paths or OS-specific bits leak into the output
    for rel, data in fa.items():
        assert b"\r\n" not in data, rel
        assert str(a).encode() not in data, rel


@pytest.mark.parametrize("name", [n for n, h in HARNESSES.items() if h.instructions_file])
def test_install_merge_is_idempotent(name, weird):
    h = HARNESSES[name]
    target = weird / h.instructions_file
    target.write_text("# My project rules\n\nkeep this\n", encoding="utf-8")
    install(name, CFG, weird)
    first = target.read_text(encoding="utf-8")
    install(name, CFG, weird)
    second = target.read_text(encoding="utf-8")
    assert first == second
    assert second.startswith("# My project rules") and "keep this" in second
    assert second.count(MARK_START) == 1 and second.count(MARK_END) == 1
    assert not (weird / f"{Path(h.instructions_file).stem}.openfusion.md").exists()


def test_install_no_instructions_leaves_files_alone(weird):
    (weird / "CLAUDE.md").write_text("mine\n", encoding="utf-8")
    install("claude-code", CFG, weird, merge_instructions=False)
    assert (weird / "CLAUDE.md").read_text(encoding="utf-8") == "mine\n"
    assert (weird / "CLAUDE.openfusion.md").exists()


def test_install_missing_repo(tmp_path):
    with pytest.raises(FileNotFoundError):
        install("cursor", CFG, tmp_path / "does not exist")


def test_install_codex_profiles_never_overwrite(weird, tmp_path):
    home = tmp_path / "codex home"
    home.mkdir()
    (home / "fusion-fast.config.toml").write_text("# mine\n", encoding="utf-8")
    install("codex", CFG, weird, codex_profiles_home=home)
    assert (home / "fusion-fast.config.toml").read_text(encoding="utf-8") == "# mine\n"
    assert (home / "fusion-deep.config.toml").exists()


def test_checked_in_adapters_match_render(tmp_path):
    render_all(CFG, tmp_path)
    fresh, repo = files(tmp_path), files(ROOT / "adapters")
    assert fresh == repo, "adapters/ is stale: run `python -m openfusion render all --out adapters`"


def test_cli_render_and_install(weird, capsys):
    assert main(["harnesses"]) == 0
    assert "github-copilot" in capsys.readouterr().out
    assert main(["render", "gemini-cli", "--out", str(weird / "out")]) == 0
    assert (weird / "out/.gemini/agents/fusion-deep.md").exists()
    repo = weird / "repo"
    repo.mkdir()
    assert main(["install", "opencode", str(repo)]) == 0
    assert "installed" in capsys.readouterr().out
    assert MARK_START in (repo / "AGENTS.md").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["install", "nope", str(repo)])


def test_launcher_runs_from_checkout(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "run_openfusion.py"), "route", "add a /health endpoint"],
                         capture_output=True, text=True, cwd=str(tmp_path), check=True).stdout
    assert out.startswith("feature: standard")
