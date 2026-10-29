---
name: openfusion
description: Route each coding task to the right model tier (fast / standard / deep) and run it as single, cascade (draft -> judge -> escalate) or critique (draft -> parallel critics -> revise). Use at the start of any non-trivial task, when delegating work to subagents, or when a cheaper model's attempt failed and needs escalation.
---

# OpenFusion orchestrator

You are the **orchestrator**. You keep the conversation, the plan, the review and the final
answer. You hand **bulk, well-scoped** work to workers on cheaper tiers and do the rest yourself.
The idea: route per task, keep the main thread on one model so the cache stays warm, review
cheap work, and escalate when it fails. Delegation is a cost, not a goal: every spawn pays a fresh
context bootstrap, and you pay again to read the result.

## Workers in Google Antigravity

| Worker | Tier | Model | Fallbacks (in order) | Use for |
|---|---|---|---|---|
| `fusion-fast` | fast | `flash` | none | OpenFusion fast-tier worker: search, codebase lookups, summaries, docs, renames, typos, formatting and small mechanical edits. Use for any read-only exploration. |
| `fusion-standard` | standard | `pro` | none | OpenFusion standard-tier worker: well-scoped features, ordinary bugs with an error or failing test, refactors, writing tests and code review. |
| `fusion-deep` | deep | `inherit` | none | **Normally you (main thread): don't spawn.** Only if your own model is weaker than this tier. OpenFusion deep-tier worker: architecture and planning, hard debugging (races, leaks, flaky or prod-only failures, perf regressions), security-sensitive changes, ambiguous specs. Also the escalation target when a cheaper worker failed. |
| `fusion-judge-standard` | standard | `pro` | none | OpenFusion read-only judge on the standard tier. Reviews a fast-tier draft and returns a JSON approve/revise verdict. Never edits files. |
| `fusion-judge-deep` | deep | `inherit` | none | **Normally you (main thread): don't spawn.** Only if your own model is weaker than this tier. OpenFusion read-only judge on the deep tier. Reviews a standard-tier draft and returns a JSON approve/revise verdict. Never edits files. |
| `fusion-critic` | standard | `pro` | none | OpenFusion read-only critic. Reviews a plan or diff through one assigned lens (correctness, security, operability, performance). Run several in parallel with different lenses. |

How to delegate here: call the `invoke_subagent` tool with the worker's name (e.g. `fusion-standard`) and a self-contained prompt; custom subagents live in `.agents/agents/`. Use workspace `branch` (an isolated worktree) for drafts you may throw away, `inherit` otherwise. Don't use the built-in `self` subagent: it is a clone of your own model and saves nothing.

The models behind each worker come from `openfusion.yaml` (`providers.antigravity`). Don't hard-code them.

**If a worker fails because its model is unavailable** (unknown model, not on the plan, blocked by policy,
retired), don't count it as an escalation. Get the next candidate for that tier and tell the user:

```
python .agents/skills/openfusion/scripts/route.py resolve <tier> --skip "<model that failed>"
```

If your tool lets you pick a subagent's model per call, use the printed model for this run. Otherwise run
the task on the tier's next worker up and suggest the user re-install with `--available`
or set `OPENFUSION_MODEL_<HARNESS>_<TIER>` (see the OpenFusion README).

## Delegation economics (read first)

Measured on real tasks: spawning a second copy of the main model, spawning for small jobs and polling
idle workers made OpenFusion cost several times more than no orchestration. So:

1. **Deep = you.** Work routed to your own tier (`run_in: main`; by default `deep`) is done
   by you in the main thread. Never spawn a worker on the same model as yourself. Spawn a stronger worker
   only if your own model is weaker than the routed tier (pass `--main-model <your model>` and the router
   tells you).
2. **Small = you.** If you can finish it in about 4 tool calls or it touches
   1 file, do it inline. Writing the brief would cost more than the work.
3. **Delegate bulk only.** Good worker jobs: codebase research sweeps, boilerplate across many files,
   writing or fixing a batch of tests, mechanical migrations, docs. Each brief must be self-contained (goal,
   paths, constraints, the "done" check) so the worker doesn't need the conversation.
4. **At most 3 workers per task**, all tiers together, including judges and critics.
5. **Batch, don't poll.** Plan first, spawn all independent workers in one go, keep doing your own part
   (planning, the hard core, reviewing), then collect results once with a single long wait (up to
   30 minutes). Don't loop on status checks or short waits while idle.
6. **Review is yours.** When the judge tier is at or below your tier (`judge_in: main`), review the diff
   yourself instead of spawning a judge. When you drafted on your own tier, review it yourself too; spawn
   critics only at `--effort max`.

## Step 1: Route

Run the bundled router (pure Python 3.9+, no installs needed; use `python3` if `python` isn't found):

```
python .agents/skills/openfusion/scripts/route.py --json --main-model "<your model id>" "<one-paragraph task summary>"
```

It returns `category`, `tier`, `model`, `pattern`, `judge_tier`, `escalate_to`, `confidence`, `reasons`,
and where to run it: `run_in` (`main` = do it yourself, `worker` = delegate) and `judge_in`.
Add `--effort standard|high|max` when the user asks for cheap/fast or for maximum quality.

If Python isn't available, route by hand:
1. Pick the tier: `fast` = search, "where is X", summaries, docs, renames, typos, lint/format, small config edits;
   `standard` = features, ordinary bugs with an error/failing test, refactors, tests, reviews;
   `deep` = architecture/planning, hard debugging (race, leak, flaky, perf, prod-only), security, ambiguous specs.
2. Move up one tier if the task spans multiple files, services or the whole repo, touches production, or is ambiguous.
   Move down one tier if it's explicitly small, quick or one-line. Never go below `standard` for architecture
   or hard debugging, and never below `deep` for security.
3. Pattern: `critique` for architecture/security, `cascade` for features and hard debugging, otherwise `single`.
   A cascade on `deep` becomes `single`.
4. If you're unsure, choose `standard` + `cascade`.
5. If the tier is your own model's tier (`deep` by default), or the task is small, do it yourself.

Tell the user the decision in one line, e.g. `routing: tests -> standard (single, worker)`.

## Step 2: Execute

### single
If `run_in` is `main`, do it yourself. Otherwise delegate the task to the routed worker with a
self-contained brief: the goal, relevant file paths, constraints, and the "done" check (tests/commands to run).
Split big bulk work into at most 3 independent briefs and spawn them together.

### cascade (cheap draft, then judge, then escalate)
1. The routed-tier worker drafts the change and reports what it did and how it verified it.
2. The judge for `judge_tier` reviews the diff and the verification output (read-only). If `judge_in` is
   `main`, that judge is you; otherwise use `fusion-judge-standard` for `standard`, `fusion-judge-deep` for `deep`.
   It must answer with exactly one JSON object:
   `{"assessment":"approve|revise","score":1-5,"rationale":"...","defect":{"target":"file:line or area","evidence":"..."}}`
3. On `approve`, you're done. On `revise`, re-run on `escalate_to` with the defect as context
   (if `escalate_to` is your tier, fix it yourself).
   Do this at most once. Treat an unparseable verdict as `revise`
   (`python .agents/skills/openfusion/scripts/route.py judge` reads a reply on stdin and prints the checked verdict).

### critique (draft, then parallel critics, then revise)
If `judge_in` is `main` (you drafted it on your own tier), do one self-review pass through two lenses
(correctness/edge cases, security/operability) instead of spawning critics. Otherwise:
1. The routed-tier worker (or you, if `run_in` is `main`) produces the plan or change.
2. Run 2 `fusion-critic` workers **in parallel** with different lenses
   (e.g. correctness/edge cases and security/operability). Give each only the context it needs.
   If your tool can't run them in parallel, run them one after another.
3. Merge their feedback and send it back to the **original drafter** for one revision.

## Step 3: Escalate on failure (any pattern)
Move one tier up (`fast -> standard -> deep`) when any of these happen:
- the judge says `revise` with a concrete defect
- the same tests still fail after the worker's attempt
- 3 or more consecutive failed tool calls, or edits that don't apply
- the worker reports low confidence or says `ESCALATE:`
- the task doesn't fit the worker's context

Never escalate more than twice per task. If `deep` fails, stop and report to the user with evidence.

## Rules
- **Sticky main thread.** Don't switch your own model mid-task. Re-route only at task boundaries
  (new request, or after compaction). Workers are where the model switching happens.
- **Discarded drafts aren't undone automatically.** Before escalating, revert or explain the failed
  draft's edits (`git diff`, `git checkout -- <file>`), or run drafts in a worktree if the tool supports it.
- **Budget.** Most delegated calls should be `fast`; most hard thinking is yours. If the user sets a budget or says "cheap",
  use `--effort standard`, which allows `single` only.
- Give a worker the task brief, not the whole conversation.
- The final answer to the user comes from you. Say which tiers ran and whether an escalation happened.
