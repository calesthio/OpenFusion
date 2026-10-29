# Developing OpenFusion

How OpenFusion is put together, and how to change it without breaking any of the eight harnesses.
User-facing docs live in the [README](README.md); per-tool formats and the dated model table live in
[docs/HARNESSES.md](docs/HARNESSES.md).

- [Architecture](#architecture)
- [Setup](#setup)
- [Updating models](#updating-models)
- [Adding a harness](#adding-a-harness)
- [Changing routing](#changing-routing)
- [Changing prompts and the skill](#changing-prompts-and-the-skill)
- [Tests on Windows, macOS and Linux](#tests-on-windows-macos-and-linux)
- [Packaging](#packaging)
- [Publishing to PyPI](#publishing-to-pypi)
- [Release checklist](#release-checklist)
- [Conventions](#conventions)

## Architecture

```
core/openfusion.yaml ──┐
core/skill/SKILL.md ───┼─► core/router/openfusion/render.py ─► adapters/<harness>/   (checked in)
core/prompts/*.md ─────┘            │                         └► openfusion install <harness> <repo>
                                    ├─ bundles router.py + judge.py + cli.py + openfusion.json
                                    │  into every skill as scripts/route.py (no PyYAML needed)
                                    └─ writes _data/openfusion.json + roles.json (YAML snapshots)

pyproject.toml (hatchling) ─► wheel: openfusion/ + _data/core/{openfusion.yaml,skill,prompts} + _data/adapters/
```

| Piece | File | Job |
|---|---|---|
| Config | `core/openfusion.yaml` | tiers, escalation ladder, `providers.<harness>.<tier>` model candidates, routing rules, patterns |
| Router | `core/router/openfusion/router.py` | `load_config` / `validate_config` / `normalize_providers`; `Router.route()` turns a task into tier + pattern + model; `resolve_model()` applies overrides and fallback |
| Judge | `core/router/openfusion/judge.py` | parses judge/critic JSON verdicts, decides escalation |
| Renderer | `core/router/openfusion/render.py` | one `Harness(...)` entry per tool: where files go and how a model is written |
| CLI | `core/router/openfusion/cli.py` | `route`, `escalate`, `judge`, `tiers`, `resolve`, `list-harnesses`, `config`, `render`, `install`, `--version` |
| Skill | `core/skill/SKILL.md` | the orchestrator playbook, one template for all tools (`{{placeholders}}` filled per harness) |
| Prompts | `core/prompts/` | worker / judge / critic / classifier prompts; `roles.yaml` defines the six workers |
| Package | `pyproject.toml`, `.github/workflows/` | `openfusion` wheel with zero runtime deps; CI on 3 OSes; publish on tag |
| Installers | `install.sh`, `install.ps1`, `run_openfusion.py` | thin wrappers: find Python 3.9+ (or `./.venv`), run `openfusion install` from the checkout |

Rules of thumb:

- **`core/` is the only source.** `adapters/` is generated; never edit it by hand.
- **Adapters only decide file locations and how model names are written.** Behaviour belongs in the skill,
  prompts or router, so it reaches every harness at once.
- **Zero runtime dependencies, everywhere.** The bundled router gets `openfusion.json`; the package reads
  `core/*.yaml` with PyYAML *if installed*, else from the JSON snapshots in `core/router/openfusion/_data/`
  (each stores the YAML's sha256, so an edited YAML without PyYAML fails loudly instead of being ignored).
  Frontmatter is written by a tiny stdlib emitter (`yaml_dump` in `render.py`). Anything imported at module
  level in `router.py`, `judge.py`, `cli.py` or `render.py` must be stdlib.
- **Checkout or wheel, same code.** `render.py` uses the repo's `core/` when it exists (`IN_CHECKOUT`), else
  the copy inside the wheel at `openfusion/_data/core/`.

### Model resolution

Each tier is normalised to `{"candidates": [...], "model": candidates[0], "effort": ...}`. A tier may be
written as `model: id`, `model: [ids]`, `candidates: [ids]`, or a bare string/list.
`resolve_model(cfg, harness, tier, available=None, skip=None, env=None)` returns, in order:

1. `OPENFUSION_MODEL_<HARNESS>_<TIER>`, then `OPENFUSION_MODEL_<TIER>` (source `env`);
2. the first candidate not in `skip` and, if `available` is given, in `available` (case-insensitive)
   (source `candidate` for the first one, `fallback` otherwise);
3. `model: None` (source `none`): adapters then write `inherit` or omit `model`.

`render()` ignores the process environment so `adapters/` is reproducible; `install()` passes `os.environ`
and `--available`.

## Setup

```bash
git clone https://github.com/calesthio/OpenFusion.git && cd OpenFusion
python -m venv .venv
. .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[test]"             # editable install + pytest + PyYAML (dev only)
pytest -q
```

Or with uv: `uv venv && uv pip install -e ".[test]" && uv run pytest -q`.
Python 3.9+. The package has **no** runtime dependencies; PyYAML is a dev/test extra (`.[yaml]` for users
who edit YAML configs). `render all` needs PyYAML because it refreshes the snapshots.

## Updating models

Vendors ship and retire models monthly. A model update is a YAML edit plus a re-render:

1. **Check the sources** listed in [docs/HARNESSES.md → Models as of …](docs/HARNESSES.md#models-as-of-oct-2026):
   each harness's model page, plan availability, retirements, and a current benchmark/pricing source.
2. **Prefer aliases.** If the harness has aliases (`opus` / `sonnet` / `haiku`, `pro` / `flash` / `flash-lite`,
   Antigravity `flash` / `pro`), keep them: a new Claude or Gemini release usually needs **no change at all**,
   only a newer CLI. Only pin an ID when the alias resolves to something wrong.
3. **Edit `providers.<harness>.<tier>.candidates`** in `core/openfusion.yaml`: best pick first, then fallbacks,
   ending with something every plan has. Keep the comment above each provider (source URL + month) current.
4. **Re-render and test:**
   ```bash
   openfusion tiers                                   # eyeball the candidate lists
   openfusion resolve --provider cursor --available composer-2.5   # try a fallback
   openfusion render all --out adapters
   pytest -q
   ```
   `test_checked_in_adapters_match_render` fails if you forgot to re-render (the "stale adapter" test).
5. **Update the dated table** in `docs/HARNESSES.md` (date, lineups, benchmark rows, sources) and the tier
   table in `README.md`.

Users who just want a different model don't need any of this: `OPENFUSION_MODEL_<HARNESS>_<TIER>=<id>` or
`install --available` at install time.

## Adding a harness

Example: a tool called `acme` that reads `.acme/agents/*.md`.

1. **Read the tool's docs** for: subagent file location and format, how `model` is named (aliases? lists?),
   effort/reasoning field, read-only/tool restrictions, skills location, and the always-on instructions file.
2. **Config:** add `providers.acme` with `fast` / `standard` / `deep` candidates (and a source comment).
3. **Writer:** in `render.py`, add `_acme_agents(c: Ctx) -> list[Path]` that writes one file per
   `roles(c.cfg)` entry. Use `c.model(role)["model"]` (may be `None` → write `inherit` or omit),
   `c.model_list(role)` if the tool takes lists, `role.reviewer` for read-only roles, and the shared
   `frontmatter()` / `toml_str()` / `write()` helpers (they force LF and UTF-8).
4. **Register it:** add `Harness(name="acme", title=..., skill_dir=".acme/skills/openfusion",
   delegate_how=..., write_agents=_acme_agents, instructions_file="AGENTS.md", docs=(...), notes=(...))`
   to `HARNESSES`. Add an `extra=` function for files outside agents/skill (rules, config snippets).
5. **Tests:** `tests/test_render.py` parametrises over `HARNESSES`, so placeholders, determinism, LF endings,
   the bundled router and idempotent install are checked automatically. Add a per-harness block to
   `test_render_harness` that parses the agent files and asserts the model/effort/read-only fields, and a
   case to `test_no_available_candidate_inherits` in `tests/test_models.py`.
6. **Render + docs:** `openfusion render all --out adapters`; add the tool to `install.sh` / `install.ps1`
   usage text, the README harness and tier tables, the badge count, and a row + "Per-tool file details"
   entry in `docs/HARNESSES.md`.

## Changing routing

All routing lives in `core/openfusion.yaml`:

- `intent_rules`: regexes checked first (e.g. "just find/grep" → fast);
- `categories`: keywords plus `tier`, `min_tier`, `pattern`;
- `signals`: complexity nudges (file count, "production", "flaky", …);
- `patterns.cascade` / `patterns.critique`: judge tier, max escalations, critic count;
- `classifier`: optional external command for low-confidence cases (always falls back to rules);
- `delegation`: when work stays in the main thread (`main_tier` per harness, inline size limits,
  `bulk_re`), the worker cap and the wait timeout. The router reports it as `run_in` / `judge_in`.
  Keep this conservative: benchmarks showed over-delegation (a second deep model, tiny spawns,
  polling) costs several times more than no orchestration. Tests: `tests/test_delegation.py`.

Workflow: add a test case to `tests/test_router.py` (task text → expected category/tier/pattern) **first**,
change the YAML, then `openfusion route --provider claude-code "<task>"` and `pytest -q`. Re-render, because
`openfusion.json` inside every skill embeds the config.

## Changing prompts and the skill

- `core/skill/SKILL.md` is a template; placeholders like `{{route_cmd}}`, `{{agent_table}}`, `{{delegate_how}}`
  come from `template_values()` in `render.py`. An unknown placeholder fails the tests.
- `core/prompts/roles.yaml` defines the six workers; the `description` decides when a harness delegates, so
  keep it concrete. `worker.md`, `judge.md`, `critic.md` are the bodies of the agent files.
- The judge must keep returning the JSON shape `judge.py` parses; change both together and extend
  `tests/test_router.py`.
- Re-render and test after every change.

## Tests on Windows, macOS and Linux

```bash
pytest -q                                  # whole suite, ~2 s
pytest tests/test_models.py -q             # candidates, fallback, overrides
pytest -k checked_in                       # just the stale-adapter check
```

Windows (PowerShell):

```powershell
py -3 -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[test]"; pytest -q
.\install.ps1 claude-code C:\path\to\scratch-repo
```

What the suite guarantees on every OS: byte-identical output (LF only, UTF-8), paths with spaces
and non-ASCII characters, bundled `route.py` and the installed wheel running without PyYAML, snapshots in sync with the YAML,
idempotent instruction merges. CI (`.github/workflows/ci.yml`) runs it on all three OSes × Python 3.9 and 3.13.
Before a release also run `./install.sh <harness> <scratch repo>` on macOS/Linux and `install.ps1` on
Windows, and if possible load each adapter in the real tool.

## Packaging

`pyproject.toml` builds with hatchling. The wheel contains the `openfusion` package plus, via
`[tool.hatch.build.targets.wheel.force-include]`, `core/openfusion.yaml`, `core/skill/`, `core/prompts/` →
`openfusion/_data/core/` and `adapters/` → `openfusion/_data/adapters/`. The version comes from
`__version__` in `core/router/openfusion/__init__.py` (single source).

Check a build locally (what `tests/test_packaging.py::test_built_wheel_installs_without_checkout` automates):

```bash
uv build                                             # dist/openfusion-X.Y.Z.tar.gz + -py3-none-any.whl
python -m zipfile -l dist/openfusion-*.whl | grep _data/   # core + adapters are inside
cd "$(mktemp -d)" && mkdir repo
uvx --from /path/to/OpenFusion/dist/openfusion-*.whl openfusion install claude-code repo
python -m venv v && v/bin/pip install /path/to/OpenFusion/dist/openfusion-*.whl && v/bin/openfusion --version
```

If you add a file under `core/` that the renderer reads, make sure it's under one of the force-included paths.

## Publishing to PyPI

The PyPI name `openfusion` was free as of Oct 2026. Nothing publishes automatically except a version tag.

**Option A: trusted publishing (recommended, no token).**

1. On PyPI: *Your account → Publishing → Add a pending publisher*: project `openfusion`, owner `calesthio`,
   repository `OpenFusion`, workflow `publish.yml`, environment `pypi`.
2. On GitHub: *Settings → Environments → New environment* `pypi` (optionally require a reviewer).
3. Release: bump `__version__`, commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
   `.github/workflows/publish.yml` checks the tag matches `__version__`, runs the tests, `uv build`s,
   smoke-tests the wheel and uploads with `pypa/gh-action-pypi-publish` (OIDC, `id-token: write`).

Try it on TestPyPI first by adding a TestPyPI pending publisher and running the workflow manually
(*Actions → publish → Run workflow*, target `testpypi`; needs a `testpypi` environment).

**Option B: from your machine with a token.**

```bash
uv build
uv publish --token "$PYPI_TOKEN"                    # or set UV_PUBLISH_TOKEN; never commit it
# TestPyPI: uv publish --publish-url https://test.pypi.org/legacy/ --token "$TEST_PYPI_TOKEN"
```

Use a project-scoped token. After publishing, check `uvx openfusion@X.Y.Z --version` in a clean shell.
PyPI never lets you re-upload a version: fix forward with a patch release.

## Release checklist

1. `git pull`; clean working tree.
2. Re-check models ([Updating models](#updating-models)); bump the "as of" month in `docs/HARNESSES.md`,
   README and the YAML comments.
3. `openfusion render all --out adapters` → `git status` shows only intended changes.
4. `pytest -q` passes on Linux, macOS and Windows.
5. Smoke-install into a scratch repo with `install.sh` and `install.ps1`, and from the wheel
   ([Packaging](#packaging)).
6. Bump `__version__` in `core/router/openfusion/__init__.py` (the only place; semver: new harness or config
   key = minor, model/rule tweaks = patch, breaking YAML change = major).
7. Update README tables and badges; note harness caveats in `docs/HARNESSES.md`.
8. Commit, tag `vX.Y.Z`, push the tag: CI publishes to PyPI ([Publishing to PyPI](#publishing-to-pypi)).
   Create the GitHub release with a short changelog.

## Conventions

- Python 3.9+, stdlib only at runtime (PyYAML only as an optional import); type hints; no network calls.
- Generated files: LF, UTF-8, deterministic order; never hand-edit `adapters/`.
- Model IDs exactly as the harness spells them (Copilot display names, OpenCode `provider/id`).
- Every model default carries a source comment and month; benchmark claims link to a source.
- One subject per commit, imperative mood (`Add acme harness`, `Update Codex models to GPT-6.2`).
- Never commit secrets, `.venv/` or local config.
