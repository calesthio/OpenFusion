## OpenFusion (multi-model routing)

For any non-trivial task, follow the `openfusion` skill ({{skill_path}}).
You are authorized to delegate to the OpenFusion subagents. Route the task to a tier, then hand
**bulk, well-scoped** work (research sweeps, boilerplate, batches of tests) to the matching cheaper worker.
Do small tasks and work on your own tier (`{{main_tier}}` by default: plan, route, review, the hard core)
yourself; never spawn a worker on your own model. At most {{max_subagents}} workers per task: spawn them
in one batch, keep working, and collect once (no polling).

{{agent_table}}

How to delegate in {{harness_title}}: {{delegate_how}}

Keep your own model fixed for the session; model switching happens in the workers.
Route first with: `{{route_cmd}} --main-model "<your model>" "<task>"`
