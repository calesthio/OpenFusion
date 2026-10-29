<!-- Paste into AGENTS.md (`openfusion install` does this for you). -->

## OpenFusion (multi-model routing)

For any non-trivial task, follow the `openfusion` skill (`.agents/skills/openfusion/SKILL.md`).
You are authorized to delegate to the OpenFusion subagents. Route the task to a tier, then hand
**bulk, well-scoped** work (research sweeps, boilerplate, batches of tests) to the matching cheaper worker.
Do small tasks and work on your own tier (`deep` by default: plan, route, review, the hard core)
yourself; never spawn a worker on your own model. At most 3 workers per task: spawn them
in one batch, keep working, and collect once (no polling).

| Worker | Tier | Model | Effort | Fallbacks (in order) | Use for |
|---|---|---|---|---|---|
| `fusion_fast` | fast | `gpt-6-luna` | `low` | none | OpenFusion fast-tier worker: search, codebase lookups, summaries, docs, renames, typos, formatting and small mechanical edits. Use for any read-only exploration. |
| `fusion_standard` | standard | `gpt-6.1-sol` | `medium` | `gpt-6-sol` | OpenFusion standard-tier worker: well-scoped features, ordinary bugs with an error or failing test, refactors, writing tests and code review. |
| `fusion_deep` | deep | `gpt-6-astra` | `medium` | `gpt-6.1-sol` | **Normally you (main thread): don't spawn.** Only if your own model is weaker than this tier. OpenFusion deep-tier worker: architecture and planning, hard debugging (races, leaks, flaky or prod-only failures, perf regressions), security-sensitive changes, ambiguous specs. Also the escalation target when a cheaper worker failed. |
| `fusion_judge_standard` | standard | `gpt-6.1-sol` | `medium` | `gpt-6-sol` | OpenFusion read-only judge on the standard tier. Reviews a fast-tier draft and returns a JSON approve/revise verdict. Never edits files. |
| `fusion_judge_deep` | deep | `gpt-6-astra` | `medium` | `gpt-6.1-sol` | **Normally you (main thread): don't spawn.** Only if your own model is weaker than this tier. OpenFusion read-only judge on the deep tier. Reviews a standard-tier draft and returns a JSON approve/revise verdict. Never edits files. |
| `fusion_critic` | standard | `gpt-6.1-sol` | `medium` | `gpt-6-sol` | OpenFusion read-only critic. Reviews a plan or diff through one assigned lens (correctness, security, operability, performance). Run several in parallel with different lenses. |

How to delegate in Codex: call `spawn_agent` with an **explicit** `model` and `reasoning_effort` from the worker table, `fork_turns: "none"` and a self-contained `message` (start it with the worker's role prompt from `.codex/agents/<worker>.toml`, then the brief). Don't pass `agent_type` and don't ask for a custom agent by name: the multi-agent v2 spawn schema hides custom agents, so they can't be selected (openai/codex#31893, #31814), and `agent_type` can silently drop your model/effort overrides (openai/codex#32831, #33268). Never spawn a worker on your own model (e.g. a second Astra). Spawn all workers in one batch, keep working, then collect with a single `wait_agent` using a long `timeout_ms` (e.g. 1800000); the 30 s default turns into a polling loop.

Keep your own model fixed for the session; model switching happens in the workers.
Route first with: `python .agents/skills/openfusion/scripts/route.py --main-model "<your model>" "<task>"`
