# Harness reference

Where each adapter's file formats come from, and how sure we are. "Format verified" means the
frontmatter/TOML keys and folder locations match the tool's docs as of Oct 2026. Nothing here
has been run inside the real tools yet.

| Tool | Format | Docs | Not verified / caveats |
|---|---|---|---|
| Claude Code | verified | [sub-agents](https://code.claude.com/docs/en/sub-agents), [skills](https://code.claude.com/docs/en/skills), [model config](https://code.claude.com/docs/en/model-config) | Aliases need a CLI that knows the newest model (Opus 5.5 needs v2.1.280+, Sonnet 5.5 v2.1.284+, Haiku 5.5 v2.1.293+): run `claude update`. |
| Codex | verified | [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [skills](https://learn.chatgpt.com/docs/build-skills), [config-advanced](https://developers.openai.com/codex/config-advanced) | Custom agents inherit the parent sandbox (`sandbox_mode` in an agent file doesn't apply), so judge/critic are read-only only through their prompt. On multi-agent v2 custom agents **can't be selected by name**, so the skill spawns with an explicit `model` + `reasoning_effort` (see [Codex multi-agent v2](#codex-multi-agent-v2)). |
| Cursor | verified | [subagents](https://cursor.com/docs/context/subagents), [skills](https://cursor.com/docs/context/skills), [rules](https://cursor.com/docs/context/rules) | Third-party models need Premium or higher. On legacy request plans without Max Mode, subagents run on Composer regardless of `model`. `claude-sonnet-5-5` and `gemini-4-argon` follow Cursor's documented ID pattern but aren't spelled out in its docs. |
| GitHub Copilot (VS Code) | verified | [custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents), [agent file reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference), [agent skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills) | `model` is written as an ordered list of display names (`"Claude Opus 5.5 (copilot)"`, ...); VS Code uses the first available. Copilot CLI accepts lists from v1.0.83 ([github/copilot-cli#2133](https://github.com/github/copilot-cli/issues/2133)); on older builds install with `--available` to write a single name. **Unverified:** whether the `read`/`search`/`execute` tool aliases match your VS Code build. |
| Gemini CLI | verified | [subagents](https://geminicli.com/docs/core/subagents/), [creating skills](https://geminicli.com/docs/cli/creating-skills/) | Reviewers are read-only through their prompt only (no tool list set). Workspace skills load only in a trusted folder. Workers use the aliases `flash-lite` / `flash` / `pro`, resolved by gemini-cli's [`models.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/config/models.ts); aliases in subagent frontmatter are assumed to go through the same resolver. |
| Google Antigravity | verified | [custom subagents](https://antigravity.google/docs/subagents/), [skills](https://antigravity.google/docs/skills), [rules](https://antigravity.google/docs/rules/) | Subagents take a model **tier** (`flash` / `pro` / `inherit`), not a model ID: fast = `flash`, standard = `pro`, deep = `inherit` (deep work stays in the main agent). The skill never uses the built-in `self` subagent (a clone of the main model). A misspelled `tools` entry can hang a subagent (documented known issue). Whether workers without a `tools` list get the full default toolset is unverified. Shares `.agents/skills/openfusion/` with Codex and generic: install one of those three per repo. |
| OpenCode | verified | [agents](https://opencode.ai/docs/agents/), [skills](https://opencode.ai/docs/skills/), [rules](https://opencode.ai/docs/rules/) | Model IDs are `provider/model` ([models](https://opencode.ai/docs/models/)). Install with `--available-cmd "opencode models"` to keep only providers you've connected. |
| generic | n/a | [agents.md](https://agents.md) | Plain prompt files. Your agent has to load them itself. |

## Per-tool file details

- **Claude Code:** `.claude/agents/fusion-*.md` with frontmatter `name`, `description`, `model`, `effort`, and
  `tools: Read, Grep, Glob, Bash` for reviewers. The skill goes in `.claude/skills/openfusion/`, plus a block in `CLAUDE.md`.
- **Codex:** `.codex/agents/fusion_*.toml` with `name`, `description`, `model`, `model_reasoning_effort` and
  `developer_instructions`. The skill goes in `.agents/skills/openfusion/`, plus a block in `AGENTS.md`.
  - `.codex/config.openfusion.toml`: orchestrator model lines plus an `[agents]` block (`max_concurrent_threads_per_session = 3`,
    `default_subagent_model = "gpt-6-luna"`, `default_subagent_reasoning_effort = "low"`). `install` merges only the
    `[agents]` block into `.codex/config.toml` between markers, and leaves an existing `[agents]` table alone.
  - `.codex/profiles/fusion-<tier>.config.toml` holds optional profiles. `--codex-profiles` copies them to `~/.codex/`.
- **Cursor:** `.cursor/agents/fusion-*.md` with `name`, `description`, `model`, and `readonly: true` for reviewers.
  The skill goes in `.cursor/skills/openfusion/`. `.cursor/rules/openfusion.mdc` sets `alwaysApply: true`.
- **GitHub Copilot:** `.github/agents/fusion-*.agent.md` with `name`, `description`, `model`, `reasoning-effort`,
  `user-invocable: false`, and `tools: [read, search, execute]` for reviewers.
  The orchestrator `.github/agents/openfusion.agent.md` is the agent you pick. The skill goes in `.github/skills/openfusion/`.
- **Gemini CLI:** `.gemini/agents/fusion-*.md` with `name`, `description`, `kind: local` and `model`. The skill goes in
  `.gemini/skills/openfusion/`, plus a block in `GEMINI.md`.
- **Google Antigravity:** `.agents/agents/fusion-*.md` with `name`, `description`, `subagent: true`, `mainAgent: false`,
  `model` (`flash`/`pro`/`inherit`), and `tools: [view_file, grep_search, run_command]` for reviewers. The skill goes in
  `.agents/skills/openfusion/`, and `.agents/rules/openfusion.md` (`trigger: always_on`) holds the instructions.
- **OpenCode:** `.opencode/agents/fusion-*.md` with `description`, `mode: subagent`, `model`, `reasoningEffort`,
  and `permission: {edit: deny}` for reviewers. The skill goes in `.opencode/skills/openfusion/`, plus a block in `AGENTS.md`.

## Codex multi-agent v2

Benchmark (codex-openfusion, GPT-6 Astra high as the main model) before this fix: the named tier agents
couldn't be selected, so the orchestrator overrode the model by hand; the fast tier ran on Luna at medium;
60% of tokens went to a second Astra spawned as the "deep" worker; the idle main thread made 24 `wait` calls.
Net: +327% tokens vs. no orchestration. What the adapter now does, and the sources:

- **Spawn with explicit `model` + `reasoning_effort`, no `agent_type`, `fork_turns: "none"`.**
  The restricted multi-agent v2 `spawn_agent` schema hides `agent_type` (and its model/effort), so custom
  agents can't be picked by name and `task_name` only names the thread (reported on GPT-5.6; our benchmark hit
  the same on GPT-6 Astra):
  [openai/codex#31893](https://github.com/openai/codex/issues/31893) (duplicate of
  [#31814](https://github.com/openai/codex/issues/31814)).
  `features.multi_agent_v2.expose_spawn_agent_model_overrides` (on by default) exposes `model` and
  `reasoning_effort` on `spawn_agent`; overrides need a partial or context-free fork:
  [openai/codex#32749](https://github.com/openai/codex/pull/32749).
  Passing `agent_type` can discard explicit overrides when the role leaves them unset:
  [#32831](https://github.com/openai/codex/issues/32831), [#33268](https://github.com/openai/codex/issues/33268).
- **Per-tier effort is explicit.** A spawn with a model but no effort gets that model's default effort, and
  one with neither inherits the parent ([Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
  precedence: spawn value → `[agents] default_subagent_*` → parent). Fast = `gpt-6-luna` / `low`,
  standard = `gpt-6.1-sol` / `medium`.
- **Deep = the main thread.** The router returns `run_in: main` for work on the main model's tier
  (`delegation.main_tier`, default `deep`) and `judge_in: main` for reviews you can do yourself. Pass
  `--main-model` if your main model is weaker. This applies to every harness, not just Codex.
- **Fewer, bigger spawns; no polling.** The docs warn that subagent workflows consume more tokens.
  `wait_agent` defaults to a 30 s timeout (max 1 h) and its schema says to prefer long waits over busy
  polling ([`multi_agents_spec.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents_spec.rs)),
  so the skill spawns all workers at once and collects with one long `wait_agent`. At most 3 workers per task,
  also enforced by `agents.max_concurrent_threads_per_session = 3`. Tasks of about 4 tool calls or one file run inline.

## Models as of Oct 2026

Checked **2026-10-28**. Model lineups change monthly: re-check the linked pages before a release
([DEVELOPMENT.md → Updating models](../DEVELOPMENT.md#updating-models)).

### How each harness names models

| Harness | What the `model` field takes | Aliases that track new releases? | Native fallback list? | Source |
|---|---|---|---|---|
| Claude Code | alias (`haiku`, `sonnet`, `opus`, `inherit`) or full ID (`claude-opus-5-5`) | **Yes**: on the Anthropic API `opus` = Opus 5.5, `sonnet` = Sonnet 5.5, `haiku` = Haiku 5.5. Bedrock/Vertex/Foundry may map to older versions. Pin with `ANTHROPIC_DEFAULT_OPUS_MODEL` etc. | `fallbackModel` setting (up to 3), only on overload/unavailable | [model-config](https://code.claude.com/docs/en/model-config), [sub-agents](https://code.claude.com/docs/en/sub-agents) |
| Codex | exact ID (`gpt-6.1-sol`) + `model_reasoning_effort` (low … ultra) | No | No | [models](https://learn.chatgpt.com/docs/models), [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) |
| GitHub Copilot | display name `"Name (copilot)"`, **string or list** | Server-side catalog; retired models point to a "latest" replacement; Auto model selection | **Yes**: first available in the list | [supported models](https://docs.github.com/en/copilot/reference/ai-models/supported-models), [auto model selection](https://docs.github.com/en/copilot/concepts/auto-model-selection), [custom agent file](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference) |
| Cursor | `inherit` or one ID, params in brackets (`claude-opus-5-5[effort=high]`) | No | Cursor falls back to a compatible model when one is blocked or off-plan | [models](https://cursor.com/docs/models), [subagents](https://cursor.com/docs/context/subagents) |
| Gemini CLI | alias (`auto`, `pro`, `flash`, `flash-lite`) or ID; default `inherit` | **Yes**: `pro` → gemini-3.1-pro-preview, `flash` → gemini-3.8-flash, `flash-lite` → gemini-3.5-flash-lite (depends on account access) | No | [subagents](https://geminicli.com/docs/core/subagents/), [model](https://geminicli.com/docs/cli/model), [models.ts](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/config/models.ts) |
| Google Antigravity | only `flash`, `pro` or `inherit` | **Yes** (tiers, not IDs) | No | [subagents](https://antigravity.google/docs/subagents/), [models](https://antigravity.google/docs/models) |
| OpenCode | `provider/model-id` (`anthropic/claude-opus-5-5`, `openai/gpt-6.1-sol`, Zen `opencode/...`) | No; `opencode models` lists what you have | No | [agents](https://opencode.ai/docs/agents/), [models](https://opencode.ai/docs/models/) |

### What each harness offers (Oct 2026)

- **Claude Code:** Haiku 5.5, Sonnet 5.5, Opus 5.5 (and older Opus 5 / 4.x by full ID). Effort: low, medium,
  high, xhigh, max; Anthropic notes Opus 5.5 at medium is roughly Opus 5 at high.
- **Codex:** `gpt-6-astra` (frontier), `gpt-6.1-sol` (recommended default), `gpt-6.1-terra` (CLI 0.159+),
  `gpt-6-luna` (fast). GPT-5.5 retired 2026-10-14, gpt-5.4 on 2026-08-31.
- **GitHub Copilot:** GPT-6 Astra / Luna / Sol, GPT-6.1 Sol / Terra, GPT-5.6, GPT-5.3-Codex (LTS); Claude
  Opus 5.5 / 5 / 4.8, Sonnet 5.5, Haiku 5.5, Fable 5 / 5.1; Gemini 4 Argon, Gemini 3.8 Flash; Grok 4.5–4.7;
  Kimi K3; MAI. The Pro plan doesn't include Opus 5.x, Fable, GPT-6 Astra, the Sol models or Gemini 4 Argon.
- **Cursor:** Composer 2.5 and Grok 4.5–4.7 (Cursor-hosted); third-party (Premium+): Claude Opus 5.5
  ($4/$20 per M tokens), Sonnet 5.5 ($2/$10), Haiku 5.5 ($0.10/$0.50), Fable 5.1; GPT-5.6 Luna / Terra / Sol;
  Gemini 4 Argon, Gemini 3.8 Flash. No GPT-6 models.
- **Gemini CLI:** Gemini 3.1 Pro (preview), 3.8 Flash, 3.5 Flash-Lite through aliases. Gemini 4 Argon
  (`gemini-4-argon`) is GA on the API since 2026-10-13, but Gemini CLI 0.66 notes it is not yet tuned for
  Gemini 4, so `pro` stays on 3.1 Pro for now. Unpaid users moved to Antigravity CLI on 2026-06-18.
- **Google Antigravity:** subagents pick `flash` or `pro`; the main agent can run Gemini 4 Argon (paid plans),
  Gemini 3.8 Flash, or Claude Sonnet 5.5 / Opus 5.5 (Pro non-trial and Ultra). Opus 4.6, Sonnet 4.6 and
  GPT-OSS-120b are removed on 2026-11-02.
- **OpenCode:** any connected provider; the defaults use Anthropic, then OpenAI, then Google.

### Why these tier picks

| Evidence | Opus 5.5 | GPT-6 Astra | GPT-6.1 Sol | Sonnet 5.5 | Gemini 4 Argon |
|---|---|---|---|---|---|
| Artificial Analysis Intelligence Index v5 | 58 (max) | 57 (max) | 55 (max) | 54 | 50 |
| Cost per Index task | $10.04 (max) | $6.25 (max) | | | $7.68 |
| Terminal-Bench 4.0 | 66.4 | 57.7 | | | |
| HLE with tools | 67.7 | 57.2 | | | |
| AutomationBench | 40.0 | 41.4 | | | |
| API price, input/output per M tokens | $4 / $20 | $10 / $50 | | $2 / $10 | $2 / $10 |

Sources: [Artificial Analysis, 2026-10-28](https://artificialanalysis.ai/articles/gemini-4-carbon-new-number-1)
(its Coding Agent Index also has Claude Code + Opus 5.5 on top at 62);
[Vellum, Opus 5.5 vs GPT-6 Astra, 2026-09-23](https://vellum.ai/blog/claude-opus-5-5-vs-gpt-6-astra);
[Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing); [OpenAI pricing](https://developers.openai.com/api/docs/pricing).

- **deep:** Opus 5.5 and GPT-6 Astra are the same class (57 vs 58). Opus 5.5 leads on coding and terminal work
  and costs less per token; Astra leads on math and is cheaper per task at max effort. Where both exist
  (Copilot, OpenCode) Opus 5.5 comes first and Astra second, so either works and you get the other as a fallback.
- **standard:** Sonnet 5.5 or GPT-6.1 Sol: about 95% of the deep model's score at a fraction of the price.
- **fast:** Haiku 5.5 and GPT-6 Luna both cost $0.10 / $0.50; Gemini 3.8 Flash ($0.75 / $3.75) is the
  third choice. On Cursor, Composer 2.5 ($0.50 / $2.50) is in every plan, so it comes first.

### Keeping models current

1. **Aliases do most of the work.** Claude Code, Gemini CLI and Antigravity get new models through their
   aliases with no change to OpenFusion; just keep the CLI updated.
2. **Ordered candidates cover the rest.** Each tier lists a best pick and fallbacks. Copilot uses the list
   natively; `install --available` picks for other harnesses; `route.py resolve <tier> --skip <model>` picks at run time.
3. **Overrides need no edit.** `OPENFUSION_MODEL_<HARNESS>_<TIER>` or `OPENFUSION_MODEL_<TIER>` win over the YAML.
4. **A dated table** (this section) and a release checklist item keep the defaults honest.

