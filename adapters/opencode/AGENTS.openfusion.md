<!-- Paste into AGENTS.md (`openfusion install` does this for you). -->

## OpenFusion (multi-model routing)

For any non-trivial task, follow the `openfusion` skill (`.opencode/skills/openfusion/SKILL.md`).
You are authorized to delegate to the OpenFusion subagents. Route the task to a tier, then hand
**bulk, well-scoped** work (research sweeps, boilerplate, batches of tests) to the matching cheaper worker.
Do small tasks and work on your own tier (`deep` by default: plan, route, review, the hard core)
yourself; never spawn a worker on your own model. At most 3 workers per task: spawn them
in one batch, keep working, and collect once (no polling).

| Worker | Tier | Model | Fallbacks (in order) | Use for |
|---|---|---|---|---|
| `fusion-fast` | fast | `anthropic/claude-haiku-5-5` | `openai/gpt-6-luna`, `google/gemini-3.8-flash` | OpenFusion fast-tier worker: search, codebase lookups, summaries, docs, renames, typos, formatting and small mechanical edits. Use for any read-only exploration. |
| `fusion-standard` | standard | `anthropic/claude-sonnet-5-5` | `openai/gpt-6.1-sol`, `opencode/gpt-6.1-sol` | OpenFusion standard-tier worker: well-scoped features, ordinary bugs with an error or failing test, refactors, writing tests and code review. |
| `fusion-deep` | deep | `anthropic/claude-opus-5-5` | `openai/gpt-6-astra`, `google/gemini-4-argon` | **Normally you (main thread): don't spawn.** Only if your own model is weaker than this tier. OpenFusion deep-tier worker: architecture and planning, hard debugging (races, leaks, flaky or prod-only failures, perf regressions), security-sensitive changes, ambiguous specs. Also the escalation target when a cheaper worker failed. |
| `fusion-judge-standard` | standard | `anthropic/claude-sonnet-5-5` | `openai/gpt-6.1-sol`, `opencode/gpt-6.1-sol` | OpenFusion read-only judge on the standard tier. Reviews a fast-tier draft and returns a JSON approve/revise verdict. Never edits files. |
| `fusion-judge-deep` | deep | `anthropic/claude-opus-5-5` | `openai/gpt-6-astra`, `google/gemini-4-argon` | **Normally you (main thread): don't spawn.** Only if your own model is weaker than this tier. OpenFusion read-only judge on the deep tier. Reviews a standard-tier draft and returns a JSON approve/revise verdict. Never edits files. |
| `fusion-critic` | standard | `anthropic/claude-sonnet-5-5` | `openai/gpt-6.1-sol`, `opencode/gpt-6.1-sol` | OpenFusion read-only critic. Reviews a plan or diff through one assigned lens (correctness, security, operability, performance). Run several in parallel with different lenses. |

How to delegate in OpenCode: use the task tool with the agent name, or mention it (e.g. `@fusion-standard ...`).

Keep your own model fixed for the session; model switching happens in the workers.
Route first with: `python .opencode/skills/openfusion/scripts/route.py --main-model "<your model>" "<task>"`
