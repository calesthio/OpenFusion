"""openfusion CLI: route | escalate | judge | tiers | resolve | harnesses | render | install

Pure Python + pathlib; behaves the same on Windows, macOS and Linux.
Standard library only. route/escalate/judge/tiers also run from the copy bundled inside every
rendered skill (JSON config); render/install need the checkout or the installed wheel.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import __version__
from .judge import parse_verdict
from .router import Router, find_config, load_config, next_tier, resolve_model


def parse_available(values: list[str] | None, cmd: str | None = None) -> list[str] | None:
    """--available a,b --available @models.txt --available-cmd "opencode models" -> ['a', 'b', ...].

    Files and command output are read one model per line (blank lines and '#' comments ignored);
    inline values are comma-separated. None means "not given" (no filtering)."""
    if not values and not cmd:
        return None
    out: list[str] = []
    for v in values or []:
        if v.startswith("@"):
            lines = Path(v[1:]).expanduser().read_text(encoding="utf-8").splitlines()
            out += [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
        else:
            out += [x.strip() for x in v.split(",") if x.strip()]
    if cmd:
        res = subprocess.run(cmd if os.name == "nt" else shlex.split(cmd), capture_output=True, text=True,
                             timeout=60, check=False, shell=os.name == "nt")
        if res.returncode != 0:
            raise SystemExit(f"--available-cmd failed ({res.returncode}): {res.stderr.strip()[:300]}")
        out += [ln.strip() for ln in res.stdout.splitlines() if ln.strip() and not ln.startswith("#")]
    return out


def _add_available(p: argparse.ArgumentParser) -> None:
    p.add_argument("--available", action="append", metavar="MODELS",
                   help="models you can use: comma list, or @file with one per line (repeatable)")
    p.add_argument("--available-cmd", metavar="CMD",
                   help='command that prints one available model per line, e.g. "opencode models"')


def _render_mod():
    try:
        from . import render
    except ImportError as exc:  # bundled copy (no render module / no PyYAML)
        raise SystemExit(f"render/install need the full OpenFusion package: `uvx openfusion ...` or "
                         f"`pip install openfusion` ({exc})")
    return render


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="openfusion", description="Route coding tasks to model tiers.")
    ap.add_argument("--version", action="version", version=f"openfusion {__version__}")
    ap.add_argument("--config", help="path to openfusion.yaml/.json (default: core/openfusion.yaml or $OPENFUSION_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("route", help="classify a task into a tier/pattern")
    r.add_argument("task", nargs="*", help="task description (or stdin)")
    r.add_argument("--provider", help="harness whose model names to show (claude-code, codex, cursor, ...)")
    r.add_argument("--effort", choices=["standard", "high", "max"])
    r.add_argument("--main-model", help="your own (orchestrator) model, e.g. gpt-6-astra: work on its tier stays in the main thread")
    r.add_argument("--main-tier", choices=None, help="tier of your own model (fast|standard|deep); overrides --main-model")
    r.add_argument("--json", action="store_true", help="full JSON output")

    e = sub.add_parser("escalate", help="print the next tier up")
    e.add_argument("tier")
    e.add_argument("--provider")

    sub.add_parser("judge", help="validate a judge reply (stdin) -> approve/revise")
    sub.add_parser("tiers", help="show tier -> model candidates for every harness")

    rs = sub.add_parser("resolve", help="pick the model for a tier: env override, else first available candidate")
    rs.add_argument("tier", nargs="?", help="tier (default: every tier)")
    rs.add_argument("--provider", help="harness (default: the bundled skill's harness)")
    rs.add_argument("--skip", action="append", default=[], metavar="MODEL",
                    help="treat this model as unavailable (repeatable), e.g. after an 'unknown model' error")
    rs.add_argument("--json", action="store_true")
    _add_available(rs)
    sub.add_parser("list-harnesses", aliases=["harnesses"], help="list supported harnesses and where files go")
    cf = sub.add_parser("config", help="print the active config, to save and customize: "
                                       "openfusion config > my.yaml, then openfusion --config my.yaml install ...")
    cf.add_argument("--json", action="store_true", help="print it as JSON (editable without PyYAML)")
    cf.add_argument("--path", action="store_true", help="only print where the active config lives")

    rd = sub.add_parser("render", help="write adapter files for a harness (or 'all') into a folder")
    rd.add_argument("harness", help="harness name or 'all'")
    rd.add_argument("--out", required=True, help="output folder (for 'all': one subfolder per harness)")

    ins = sub.add_parser("install", help="install a harness adapter into a repo")
    ins.add_argument("harness")
    ins.add_argument("repo", nargs="?", default=".", help="path to the target repo (default: current folder)")
    ins.add_argument("--no-instructions", action="store_true",
                     help="don't touch CLAUDE.md / AGENTS.md / GEMINI.md; write *.openfusion.md next to it instead")
    ins.add_argument("--codex-profiles", action="store_true",
                     help="codex only: also copy fusion-*.config.toml profiles into ~/.codex/")
    _add_available(ins)

    a = ap.parse_args(argv)
    if a.cmd == "config" and not a.json:
        src = Path(a.config or os.environ.get("OPENFUSION_CONFIG") or find_config())
        print(src if a.path else src.read_text(encoding="utf-8"), end="\n" if a.path else "")
        return 0
    cfg = load_config(a.config)
    if a.cmd == "config":
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return 0

    if a.cmd == "route":
        task = " ".join(a.task) if a.task else sys.stdin.read()
        if not task.strip():
            ap.error("empty task")
        try:
            d = Router(cfg).route(task, effort=a.effort, provider=a.provider,
                                  main_model=a.main_model, main_tier=a.main_tier)
        except ValueError as exc:
            ap.error(str(exc))
        if a.json:
            print(json.dumps(d.to_dict(), indent=2))
        else:
            model = f" -> {d.model['model']}" if d.model else ""
            judge = f", judge={d.judge_tier}" if d.judge_tier else ""
            where = "main thread (do it yourself)" if d.run_in == "main" else "worker"
            jw = f", judge in {d.judge_in}" if d.judge_in else ""
            print(f"{d.category}: {d.tier}{model} ({d.pattern}{judge}, confidence {d.confidence}) "
                  f"-> run in {where}{jw}")
        return 0
    if a.cmd == "escalate":
        nt = next_tier(cfg, a.tier)
        if nt is None:
            print("none: already at top tier", file=sys.stderr)
            return 1
        print(json.dumps({"tier": nt, "model": resolve_model(cfg, a.provider, nt)}) if a.provider else nt)
        return 0
    if a.cmd == "judge":
        try:
            v = parse_verdict(sys.stdin.read())
        except ValueError as exc:
            print(json.dumps({"assessment": "revise", "error": str(exc)}))
            return 2
        print(json.dumps(v))
        return 0 if v["assessment"] == "approve" else 2
    if a.cmd == "tiers":
        for prov, m in cfg["providers"].items():
            print(prov + ": " + ", ".join(f"{t}={' > '.join(m[t]['candidates'])}" for t in cfg["escalation_ladder"]))
        return 0
    if a.cmd == "resolve":
        provider = a.provider or cfg.get("default_provider")
        if not provider:
            ap.error("--provider is required here (bundled skills default to their own harness)")
        tiers = [a.tier] if a.tier else list(cfg["escalation_ladder"])
        try:
            avail = parse_available(a.available, a.available_cmd)
            res = {t: resolve_model(cfg, provider, t, available=avail, skip=a.skip) for t in tiers}
        except ValueError as exc:
            ap.error(str(exc))
        if a.json:
            print(json.dumps(res if not a.tier else res[a.tier], indent=2))
        else:
            for t, m in res.items():
                print(f"{t}: {m['model'] or 'inherit (no candidate available)'} [{m['source']}]")
        return 0 if all(m["model"] for m in res.values()) else 1

    rm = _render_mod()
    if a.cmd in ("harnesses", "list-harnesses"):
        for h in rm.HARNESSES.values():
            print(f"{h.name:15} {h.status:10} skill: {h.skill_dir}")
        return 0
    if a.cmd == "render":
        if a.harness == "all":
            for name, paths in rm.render_all(cfg, Path(a.out)).items():
                print(f"{name}: {len(paths)} files")
            if rm.IN_CHECKOUT and not a.config:
                try:
                    snaps = rm.write_snapshots()
                    print(f"snapshots: {', '.join(p.name for p in snaps)} (package data, for installs without PyYAML)")
                except ImportError:
                    print("snapshots: skipped (PyYAML not installed)", file=sys.stderr)
            return 0
        if a.harness not in rm.HARNESSES:
            ap.error(f"unknown harness {a.harness!r}; choose from {list(rm.HARNESSES)} or 'all'")
        for p in rm.render(a.harness, cfg, Path(a.out)):
            print(p)
        return 0
    if a.cmd == "install":
        if a.harness not in rm.HARNESSES:
            ap.error(f"unknown harness {a.harness!r}; choose from {list(rm.HARNESSES)}")
        home = Path.home() / ".codex" if a.codex_profiles else None
        try:
            paths, steps = rm.install(a.harness, cfg, Path(a.repo), merge_instructions=not a.no_instructions,
                                      codex_profiles_home=home,
                                      available=parse_available(a.available, a.available_cmd),
                                      env=dict(os.environ))
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        repo = Path(a.repo).expanduser().resolve()
        print(f"OpenFusion {a.harness} adapter installed into {repo} ({len(paths)} files).")
        print("Next steps:")
        for s in steps:
            print(f"  - {s}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
