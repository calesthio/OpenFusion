"""The installable package: zero runtime deps, data files in the wheel, `openfusion install` without a checkout."""
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest
import yaml

import openfusion
from openfusion import router
from openfusion.cli import main
from openfusion.render import SNAPSHOTS, frontmatter, yaml_dump

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", sorted(SNAPSHOTS))
def test_snapshots_match_yaml(name):
    """_data/*.json lets the package run without PyYAML; `openfusion render all` refreshes it."""
    src = SNAPSHOTS[name]
    snap = json.loads((router.DATA / name).read_text(encoding="utf-8"))
    text = src.read_text(encoding="utf-8")
    assert snap["source_sha256"] == router.source_digest(text), "stale: run `openfusion render all --out adapters`"
    assert snap["data"] == yaml.safe_load(text)


def test_load_yaml_without_pyyaml(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "yaml", None)  # import yaml -> ImportError
    cfg = router.load_config(ROOT / "core" / "openfusion.yaml")
    assert cfg["providers"]["claude-code"]["deep"]["model"] == "opus"
    edited = tmp_path / "openfusion.yaml"
    edited.write_text((ROOT / "core" / "openfusion.yaml").read_text(encoding="utf-8") + "\n# edited\n",
                      encoding="utf-8")
    with pytest.raises(SystemExit, match="PyYAML"):
        router.load_config(edited)


@pytest.mark.parametrize("value", [
    "plain words", "has: colon", "#hash", "- dash", "yes", "No", "null", "5.5", "0x10", "2026-10-28",
    "Claude Opus 5.5 (copilot)", "claude-opus-5-5[effort=high]", "<small-model>", "it's \"quoted\"",
    "trailing ", "ünïcode — dash", "a\nb", "", "@at", "*star", "&amp", "!bang", "%pct", "{brace}", "[x]",
])
def test_yaml_dump_roundtrips(value):
    data = {"name": value, "list": [value, "x"], "nested": {"edit": value}, "flag": True, "n": 3, "empty": []}
    assert yaml.safe_load(yaml_dump(data)) == data


def test_frontmatter_shape():
    text = frontmatter({"name": "a", "tools": ["read", "search"]}, "\nbody\n")
    assert text == "---\nname: a\ntools:\n- read\n- search\n---\n\nbody\n"


def test_runtime_modules_are_stdlib_only():
    for mod in ("router.py", "judge.py", "cli.py", "render.py", "__init__.py"):
        src = (ROOT / "core/router/openfusion" / mod).read_text(encoding="utf-8")
        assert "\nimport yaml" not in src and "\nfrom yaml" not in src, mod


def test_cli_version_and_list_harnesses(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0 and capsys.readouterr().out.strip() == f"openfusion {openfusion.__version__}"
    assert main(["list-harnesses"]) == 0
    out = capsys.readouterr().out
    assert "claude-code" in out and "opencode" in out


def test_cli_install_defaults_to_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["install", "gemini-cli"]) == 0
    assert (tmp_path / ".gemini/agents/fusion-deep.md").is_file()


def test_pyproject_metadata():
    try:
        import tomllib
    except ImportError:
        pytest.skip("tomllib needs Python 3.11+")
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["name"] == "openfusion" and meta["dependencies"] == []
    assert meta["requires-python"] == ">=3.9" and meta["license"] == "MIT"
    assert meta["scripts"]["openfusion"] == "openfusion.cli:main"
    assert all(u.startswith("https://github.com/calesthio/OpenFusion") for u in meta["urls"].values())


@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv (https://docs.astral.sh/uv/)")
def test_built_wheel_installs_without_checkout(tmp_path):
    """uv build -> fresh venv without PyYAML -> `openfusion install` from outside the repo."""
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)], check=True,
                   capture_output=True, text=True)
    wheel = next(dist.glob("openfusion-*.whl"))
    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    py = bindir / ("python.exe" if os.name == "nt" else "python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-index", str(wheel)], check=True)
    repo = tmp_path / "some repo"
    repo.mkdir()
    exe = bindir / ("openfusion.exe" if os.name == "nt" else "openfusion")
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPENFUSION_", "PYTHON"))}
    run = lambda *a: subprocess.run([str(exe), *a], cwd=tmp_path, env=clean, check=True,  # noqa: E731
                                    capture_output=True, text=True).stdout
    assert run("--version").strip() == f"openfusion {openfusion.__version__}"
    assert "installed" in run("install", "claude-code", str(repo))
    assert (repo / ".claude/agents/fusion-deep.md").is_file() and (repo / "CLAUDE.md").is_file()
    probe = subprocess.run([str(py), "-c", "import yaml"], capture_output=True)
    assert probe.returncode != 0, "PyYAML must not be a runtime dependency"
    data = subprocess.run([str(py), "-c", "import openfusion.render as r; print(r.CORE)"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert Path(data).parts[-2:] == ("_data", "core") and not Path(data).is_relative_to(ROOT)
    wheel_adapters = Path(data).parent / "adapters" / "claude-code" / ".claude" / "agents" / "fusion-deep.md"
    assert wheel_adapters.read_text(encoding="utf-8") == \
        (ROOT / "adapters/claude-code/.claude/agents/fusion-deep.md").read_text(encoding="utf-8")


def test_config_export_roundtrip(tmp_path, capsys):
    """`openfusion config --json > my.json` is a customizable config that needs no PyYAML."""
    assert main(["config", "--path"]) == 0
    assert capsys.readouterr().out.strip().endswith("openfusion.yaml")
    assert main(["config"]) == 0
    assert "providers:" in capsys.readouterr().out
    assert main(["config", "--json"]) == 0
    cfg = json.loads(capsys.readouterr().out)
    cfg["providers"]["claude-code"]["deep"] = {"model": "my-deep-model"}
    custom = tmp_path / "my.json"
    custom.write_text(json.dumps(cfg), encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--config", str(custom), "install", "claude-code", str(repo)]) == 0
    assert "model: my-deep-model" in (repo / ".claude/agents/fusion-deep.md").read_text(encoding="utf-8")
