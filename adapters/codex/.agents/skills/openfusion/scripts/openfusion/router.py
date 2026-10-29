"""Rules-first task router (optional external classifier on low confidence).

Classify the task, pick a capability tier, pick an execution pattern
(single / cascade / critique), and fall back safely on any failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_PKG = Path(__file__).resolve().parent
# JSON snapshots of the YAML sources (written by `openfusion render all`), so the installed package
# needs no PyYAML. Also holds a copy of core/ and adapters/ inside a built wheel.
DATA = _PKG / "_data"
# Repo checkout: core/router/openfusion/router.py -> core/openfusion.yaml.
# Bundled copy inside a rendered skill: scripts/openfusion/router.py -> scripts/openfusion.json.
# Installed wheel: site-packages/openfusion/_data/core/openfusion.yaml.
CONFIG_CANDIDATES = (_PKG.parents[1] / "openfusion.yaml", _PKG.parent / "openfusion.json",
                     DATA / "core" / "openfusion.yaml")
DEFAULT_CONFIG = CONFIG_CANDIDATES[0]
PATTERN_DOWNGRADE = {"critique": "cascade", "cascade": "single", "single": "single"}


def find_config() -> Path:
    for cand in CONFIG_CANDIDATES:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        "openfusion config not found; pass --config or set OPENFUSION_CONFIG "
        f"(looked in {[str(c) for c in CONFIG_CANDIDATES]})")


def source_digest(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def load_yaml(path: Path) -> Any:
    """Parse YAML with PyYAML when it's installed; otherwise use the JSON snapshot in _data/
    (valid only while the YAML is unchanged since the last `openfusion render all`)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:
        snap = DATA / f"{Path(path).stem}.json"
        if snap.is_file():
            data = json.loads(snap.read_text(encoding="utf-8"))
            if data.get("source_sha256") == source_digest(text):
                return data["data"]
        raise SystemExit(
            f"{path} differs from OpenFusion's built-in copy, and reading an edited YAML file needs PyYAML: "
            "`pip install pyyaml` (or `uvx --with pyyaml openfusion ...`), or pass a .json config.") from None
    return yaml.safe_load(text)


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Load YAML or JSON config. JSON needs no third-party packages (used by bundled copies)."""
    path = Path(path or os.environ.get("OPENFUSION_CONFIG") or find_config())
    if path.suffix.lower() == ".json":
        cfg = json.loads(path.read_text(encoding="utf-8"))
    else:
        cfg = load_yaml(path)
    normalize_providers(cfg)
    validate_config(cfg)
    return cfg


# --------------------------------------------------------------------------- model candidates
def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]


def normalize_providers(cfg: dict[str, Any]) -> dict[str, Any]:
    """Accept `model: x`, `model: [x, y]` or `candidates: [x, y]` per tier.

    After this every tier entry has `candidates` (ordered, first = preferred) and `model`
    (= candidates[0]), so code that reads `entry["model"]` keeps working. Idempotent.
    """
    for pname, mapping in cfg.get("providers", {}).items():
        for tier, entry in list(mapping.items()):
            if isinstance(entry, (str, list)):
                entry = {"model": entry}
            entry = dict(entry)
            cands = _as_list(entry.get("candidates")) or _as_list(entry.get("model"))
            if not cands:
                raise ValueError(f"providers.{pname}.{tier} needs `model` or `candidates`")
            entry["candidates"] = cands
            entry["model"] = cands[0]
            mapping[tier] = entry
    return cfg


def env_override_names(provider: str, tier: str) -> tuple[str, str]:
    """OPENFUSION_MODEL_<PROVIDER>_<TIER> (most specific) then OPENFUSION_MODEL_<TIER>."""
    up = lambda s: re.sub(r"[^A-Za-z0-9]", "_", s).upper()  # noqa: E731
    return f"OPENFUSION_MODEL_{up(provider)}_{up(tier)}", f"OPENFUSION_MODEL_{up(tier)}"


def _norm(m: str) -> str:
    return re.sub(r"\s+", " ", m.strip().lower())


def resolve_model(cfg: dict[str, Any], provider: str, tier: str,
                  available: list[str] | None = None, skip: list[str] | None = None,
                  env: dict[str, str] | None = None) -> dict[str, Any]:
    """Pick the model for provider/tier.

    Order: env override > first candidate that is in `available` (if given) and not in `skip`.
    `available` / `skip` match case-insensitively. Returns a copy of the tier entry with
    `model` set and `source` = env | candidate | fallback | none.
    With `available` given and no candidate in it, returns model=None (source "none") so callers
    can fall back to the harness default (`inherit`) instead of writing a model that will fail.
    """
    if provider not in cfg["providers"]:
        raise ValueError(f"unknown provider {provider!r}; choose from {list(cfg['providers'])}")
    if tier not in cfg["providers"][provider]:
        raise ValueError(f"unknown tier {tier!r}; choose from {cfg['escalation_ladder']}")
    entry = dict(cfg["providers"][provider][tier])
    cands = list(entry["candidates"])
    env = os.environ if env is None else env
    for var in env_override_names(provider, tier):
        if env.get(var, "").strip():
            entry.update(model=env[var].strip(), source="env", override=var)
            return entry
    skipped = {_norm(s) for s in (skip or [])}
    pool = [c for c in cands if _norm(c) not in skipped]
    if available is not None:
        avail = {_norm(a) for a in available}
        pool = [c for c in pool if _norm(c) in avail]
    if pool:
        entry.update(model=pool[0], source="candidate" if pool[0] == cands[0] else "fallback")
    else:
        entry.update(model=None, source="none")
    return entry


def validate_config(cfg: dict[str, Any]) -> None:
    normalize_providers(cfg)
    ladder = cfg["escalation_ladder"]
    for name in ladder:
        if name not in cfg["tiers"]:
            raise ValueError(f"escalation_ladder tier {name!r} not defined in tiers")
    for pname, mapping in cfg["providers"].items():
        missing = [t for t in ladder if t not in mapping]
        if missing:
            raise ValueError(f"provider {pname!r} missing tiers {missing}")
    for cname, cat in cfg["categories"].items():
        for key in ("tier", "min_tier"):
            if key in cat and cat[key] not in ladder:
                raise ValueError(f"category {cname!r} has unknown {key} {cat[key]!r}")
        if cat.get("pattern", "single") not in cfg["patterns"]:
            raise ValueError(f"category {cname!r} has unknown pattern")
        for kw in cat.get("keywords", []):
            _kw(kw)
    for rule in cfg.get("intent_rules", []):
        re.compile(rule["re"])
        if rule["category"] not in cfg["categories"]:
            raise ValueError(f"intent rule points to unknown category {rule['category']!r}")
    if cfg["fallback_category"] not in cfg["categories"]:
        raise ValueError("fallback_category must be a defined category")
    for key, t in ((cfg.get("delegation") or {}).get("main_tier") or {}).items():
        if t not in ladder:
            raise ValueError(f"delegation.main_tier.{key} has unknown tier {t!r}")
    dp = cfg.get("default_provider")
    if dp is not None and dp not in cfg["providers"]:
        raise ValueError(f"default_provider {dp!r} is not in providers")
    if cfg.get("default_effort", "high") not in cfg["effort_levels"]:
        raise ValueError("default_effort must be a defined effort level")


def _kw(kw: str | dict) -> tuple[re.Pattern, int]:
    """Keyword spec: 'regex' or {re: 'regex', w: weight}."""
    if isinstance(kw, dict):
        return re.compile(kw["re"], re.I), int(kw.get("w", 1))
    return re.compile(kw, re.I), 1


def main_tier_for(cfg: dict[str, Any], provider: str | None = None, main_model: str | None = None,
                  main_tier: str | None = None, env: dict[str, str] | None = None) -> str:
    """Tier of the orchestrator's own model: explicit tier > model lookup > OPENFUSION_MAIN_TIER >
    delegation.main_tier[provider] > delegation.main_tier.default > top of the ladder."""
    ladder = cfg["escalation_ladder"]
    env = os.environ if env is None else env
    if main_tier:
        if main_tier not in ladder:
            raise ValueError(f"unknown main tier {main_tier!r}; choose from {ladder}")
        return main_tier
    if main_model:
        want = _norm(main_model)
        provs = [provider] if provider in cfg.get("providers", {}) else list(cfg.get("providers", {}))
        same = lambda a, b: a == b or a.split("/")[-1] == b.split("/")[-1]  # noqa: E731
        # A tier's preferred model first (gpt-6.1-sol is standard even if deep lists it as a fallback),
        # then fallbacks, strongest tier first.
        for primary in (True, False):
            for t in reversed(ladder):
                for p in provs:
                    cands = [_norm(c) for c in cfg["providers"][p][t]["candidates"]]
                    if any(same(want, c) for c in (cands[:1] if primary else cands[1:])):
                        return t
    if env.get("OPENFUSION_MAIN_TIER") in ladder:
        return env["OPENFUSION_MAIN_TIER"]
    mt = (cfg.get("delegation") or {}).get("main_tier") or {}
    return mt.get(provider or "", mt.get("default", ladder[-1]))


def next_tier(cfg: dict[str, Any], tier: str) -> str | None:
    """Escalation helper: the next stronger tier, or None at the top."""
    ladder = cfg["escalation_ladder"]
    i = ladder.index(tier)
    return ladder[i + 1] if i + 1 < len(ladder) else None


@dataclass
class Decision:
    category: str
    tier: str
    pattern: str
    confidence: float
    effort: str
    model: dict[str, Any] | None = None
    provider: str | None = None
    judge_tier: str | None = None
    escalate_to: str | None = None
    scores: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    source: str = "rules"
    main_tier: str | None = None
    run_in: str = "worker"            # "main" = do it yourself in the main thread, don't spawn
    judge_in: str | None = None       # "main" = you review the draft yourself


    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Router:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or load_config()
        self.ladder: list[str] = self.cfg["escalation_ladder"]
        self._cat_res = {
            name: [_kw(k) for k in c.get("keywords", [])]
            for name, c in self.cfg["categories"].items()
        }
        sig = self.cfg.get("signals", {})
        self._up = [re.compile(p, re.I) for p in sig.get("bump_up", [])]
        self._down = [re.compile(p, re.I) for p in sig.get("bump_down", [])]
        self._intents = [(re.compile(r["re"], re.I), r["category"]) for r in self.cfg.get("intent_rules", [])]

    # -- helpers ---------------------------------------------------------
    def _rank(self, tier: str) -> int:
        return self.ladder.index(tier)

    def _clamp(self, i: int) -> str:
        return self.ladder[max(0, min(i, len(self.ladder) - 1))]

    def score(self, task: str) -> dict[str, int]:
        return {n: sum(w for r, w in rs if r.search(task)) for n, rs in self._cat_res.items()}

    def _rules(self, task: str) -> tuple[str, float, dict[str, int], list[str]]:
        scores = self.score(task)
        for rx, cat in self._intents:
            if rx.search(task):
                return cat, 0.9, scores, [f"intent rule {rx.pattern!r} -> {cat!r}"]
        order = list(self.cfg["categories"])
        best = max(
            order,
            key=lambda n: (scores[n], self._rank(self.cfg["categories"][n]["tier"]), -order.index(n)),
        )
        if scores[best] == 0:
            fb = self.cfg["fallback_category"]
            return fb, 0.2, scores, [f"no rule matched -> fallback category {fb!r}"]
        total = sum(scores.values())
        conf = round(min(1.0, scores[best] / total * min(1.0, 0.5 + 0.25 * scores[best])), 2)
        hits = [r.pattern for r, _ in self._cat_res[best] if r.search(task)]
        return best, conf, scores, [f"category {best!r} matched {hits}"]

    def _classifier(self, task: str) -> dict[str, Any] | None:
        c = self.cfg.get("classifier") or {}
        if not c.get("enabled") or not c.get("command"):
            return None
        try:
            out = subprocess.run(
                c["command"], shell=True, input=task, capture_output=True,
                text=True, timeout=c.get("timeout_seconds", 5), check=True,
            ).stdout
            data = json.loads(out)
            if data.get("category") in self.cfg["categories"]:
                return data
        except (subprocess.SubprocessError, ValueError, OSError):
            pass  # Fail open: keep the rules decision.
        return None

    # -- main ------------------------------------------------------------
    def route(self, task: str, effort: str | None = None, provider: str | None = None,
              main_model: str | None = None, main_tier: str | None = None) -> Decision:
        cfg = self.cfg
        effort = effort or cfg.get("default_effort", "high")
        if effort not in cfg["effort_levels"]:
            raise ValueError(f"unknown effort {effort!r}; choose from {list(cfg['effort_levels'])}")
        level = cfg["effort_levels"][effort]

        category, conf, scores, reasons = self._rules(task)
        source = "rules"
        thr = (cfg.get("classifier") or {}).get("confidence_threshold", 0.45)
        if conf < thr:
            ext = self._classifier(task)
            if ext:
                category, conf, source = ext["category"], float(ext.get("confidence", conf)), "classifier"
                reasons.append(f"low rule confidence; classifier chose {category!r}")
        cat = cfg["categories"][category]

        # Complexity signals.
        sig = cfg.get("signals", {})
        up = [r.pattern for r in self._up if r.search(task)]
        down = [r.pattern for r in self._down if r.search(task)]
        net = len(up) - len(down)
        if len(task) >= sig.get("long_prompt_chars", 10**9):
            net += 1
            up.append("long_prompt")
        thresh = sig.get("bump_threshold", 2)
        shift = 1 if net >= thresh else -1 if net <= -thresh else 0
        if up or down:
            reasons.append(f"signals up={up} down={down} -> shift {shift:+d}")

        idx = self._rank(cat["tier"]) + shift + level.get("tier_shift", 0)
        idx = max(idx, self._rank(cat.get("min_tier", self.ladder[0])))
        idx = min(idx, self._rank(level.get("max_tier", self.ladder[-1])))
        tier = self._clamp(idx)

        pattern = cat.get("pattern", "single")
        while pattern not in level["patterns"]:
            pattern = PATTERN_DOWNGRADE[pattern]
        if pattern == "cascade" and tier == self.ladder[-1]:
            # Nothing stronger to escalate to on the top tier.
            pattern = level.get("top_tier_pattern", "single")
            reasons.append(f"cascade on top tier -> {pattern}")

        judge = None
        if pattern == "cascade":
            off = cfg["patterns"]["cascade"].get("judge_tier_offset", 1)
            judge = self._clamp(self._rank(tier) + off)
        elif pattern == "critique":
            judge = cfg["patterns"]["critique"].get("critic_tier", "standard")

        model = None
        provider = provider or cfg.get("default_provider")
        if provider:
            if provider not in cfg["providers"]:
                raise ValueError(f"unknown provider {provider!r}; choose from {list(cfg['providers'])}")
            model = resolve_model(cfg, provider, tier)  # honours OPENFUSION_MODEL_* overrides

        # Delegation economics: never hand work to a worker that is no cheaper than you.
        mt = main_tier_for(cfg, provider, main_model, main_tier)
        dl = cfg.get("delegation") or {}
        run_in = "worker"
        if tier == mt:
            run_in = "main"
            reasons.append(f"tier {tier!r} is the main thread's own tier -> do it yourself, don't spawn a copy")
        elif pattern == "single" and not up and not re.search(dl.get("bulk_re", r"(?!x)x"), task, re.I) and (
                down or (tier == self.ladder[0] and len(task) <= dl.get("inline_max_task_chars", 0))):
            run_in = "main"
            reasons.append("small, non-bulk task -> do it inline (delegation overhead exceeds the work)")
        judge_in = None
        if judge:
            if pattern == "critique":
                # Independent lenses are the point of critique; skip them only when you drafted it yourself.
                judge_in = "main" if run_in == "main" and effort != "max" else "worker"
            else:
                # You review anything up to your own tier; only a stronger judge is worth a spawn.
                judge_in = "main" if self._rank(judge) <= self._rank(mt) else "worker"
            if judge_in == "main" and pattern == "critique":
                reasons.append("you drafted it on your own tier: review it yourself (critics only at --effort max)")

        return Decision(
            category=category, tier=tier, pattern=pattern, confidence=conf,
            effort=effort, model=model, provider=provider, judge_tier=judge,
            escalate_to=next_tier(cfg, tier), scores=scores, reasons=reasons, source=source,
            main_tier=mt, run_in=run_in, judge_in=judge_in,
        )
