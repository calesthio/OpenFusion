import copy
import json
import sys

import pytest

from openfusion import Router, load_config, next_tier
from openfusion.cli import main
from openfusion.judge import parse_verdict, should_escalate

CFG = load_config()


@pytest.fixture
def router():
    return Router(CFG)


@pytest.mark.parametrize("task,category,tier", [
    ("where is the auth middleware defined", "search", "fast"),
    ("explain how the caching layer works", "search", "fast"),
    ("rename getUser to fetchUser in utils.py", "routine_edit", "fast"),
    ("quick fix: typo in error message", "routine_edit", "fast"),
    ("update the README with install steps", "docs", "fast"),
    ("fix the TypeError in checkout.ts when cart is empty", "debugging", "standard"),
    ("write unit tests for the parser module", "tests", "standard"),
    ("add a /health endpoint to the API", "feature", "standard"),
    ("refactor the payment module to extract a class", "refactor", "standard"),
    ("design the architecture for migrating our monolith to microservices", "architecture", "deep"),
    ("debug intermittent flaky test caused by a race condition", "hard_debugging", "deep"),
    ("review this PR for security issues with JWT handling", "security", "deep"),
])
def test_categories(router, task, category, tier):
    d = router.route(task)
    assert (d.category, d.tier) == (category, tier), d.reasons


def test_unknown_falls_back_to_standard(router):
    d = router.route("make it nicer")
    assert d.category == CFG["fallback_category"]
    assert d.tier == "standard"
    assert d.confidence < 0.45


def test_bump_up_signals(router):
    small = router.route("implement a CSV export endpoint")
    big = router.route("implement a CSV export across the codebase, multiple services, in production")
    assert small.tier == "standard"
    assert big.tier == "deep"


def test_bump_down_respects_security_floor(router):
    d = router.route("just a quick simple small fix for the jwt auth vulnerability")
    assert d.tier == "deep"


def test_bump_down_signals(router):
    d = router.route("just a quick small simple fix for this one function bug")
    assert d.tier == "fast"


def test_effort_standard_is_single_only(router):
    d = router.route("design the architecture for a new billing service", effort="standard")
    assert d.pattern == "single"
    d = router.route("add a /health endpoint to the API", effort="standard")
    assert d.pattern == "single" and d.judge_tier is None


def test_effort_max_shifts_up_and_critiques(router):
    d = router.route("add a /health endpoint to the API", effort="max")
    assert d.tier == "deep" and d.pattern == "critique"


def test_cascade_judge_is_one_tier_up(router):
    d = router.route("add a /health endpoint to the API")
    assert d.pattern == "cascade" and d.judge_tier == "deep" and d.escalate_to == "deep"


def test_provider_models(router):
    assert router.route("rename x to y", provider="claude-code").model["model"] == "haiku"
    assert router.route("design the architecture for X", provider="claude-code").model["model"] == "opus"
    with pytest.raises(ValueError):
        router.route("x", provider="nope")


def test_unknown_effort(router):
    with pytest.raises(ValueError):
        router.route("x", effort="ultra")


def test_next_tier():
    assert next_tier(CFG, "fast") == "standard"
    assert next_tier(CFG, "standard") == "deep"
    assert next_tier(CFG, "deep") is None


def test_classifier_used_on_low_confidence(tmp_path):
    cfg = copy.deepcopy(CFG)
    script = tmp_path / "clf.py"
    script.write_text('import json,sys; sys.stdin.read(); print(json.dumps({"category":"docs","confidence":0.8}))')
    cfg["classifier"] = {"enabled": True, "confidence_threshold": 0.45,
                         "command": f"{sys.executable} {script}", "timeout_seconds": 5}
    d = Router(cfg).route("make it nicer")
    assert d.source == "classifier" and d.category == "docs" and d.tier == "fast"


def test_classifier_failure_fails_open(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["classifier"] = {"enabled": True, "confidence_threshold": 0.45, "command": "exit 1"}
    d = Router(cfg).route("make it nicer")
    assert d.source == "rules" and d.category == CFG["fallback_category"]


def test_bad_config_rejected():
    from openfusion.router import validate_config
    cfg = copy.deepcopy(CFG)
    del cfg["providers"]["claude-code"]["deep"]
    with pytest.raises(ValueError):
        validate_config(cfg)


# -- judge -----------------------------------------------------------------
def test_judge_approve():
    v = parse_verdict('looks fine\n{"assessment":"approve","score":5,"rationale":"tests pass","defect":null}')
    assert v["assessment"] == "approve"
    assert not should_escalate('{"assessment":"approve","score":4,"rationale":"ok"}')


def test_judge_revise_needs_defect():
    with pytest.raises(ValueError):
        parse_verdict('{"assessment":"revise","score":2,"rationale":"bad"}')
    assert should_escalate('{"assessment":"revise","score":2,"rationale":"bad",'
                           '"defect":{"target":"a.py:3","evidence":"off by one"}}')


def test_judge_garbage_fails_closed():
    assert should_escalate("I think it is good!")
    assert should_escalate('{"assessment":"approve","score":9,"rationale":"x"}')


# -- cli -------------------------------------------------------------------
def test_cli_route_json(capsys):
    assert main(["route", "--json", "--provider", "codex", "rename foo to bar"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "fast" and out["model"]["model"] == CFG["providers"]["codex"]["fast"]["model"]


def test_cli_escalate(capsys):
    assert main(["escalate", "fast"]) == 0
    assert capsys.readouterr().out.strip() == "standard"
    assert main(["escalate", "deep"]) == 1


def test_cli_escalate_with_provider(capsys):
    assert main(["escalate", "fast", "--provider", "cursor"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "standard" and out["model"]["model"] == CFG["providers"]["cursor"]["standard"]["model"]


def test_default_provider_must_exist():
    from openfusion.router import validate_config
    cfg = copy.deepcopy(CFG)
    cfg["default_provider"] = "nope"
    with pytest.raises(ValueError):
        validate_config(cfg)
