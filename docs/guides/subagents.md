# SubAgents

[Documentation](../README.md) · [한국어](subagents.ko.md)

TAPL coordinates execution manifests; the Codex/root runtime creates and manages
SubAgents. Executable tasks need completed dependencies and exclusive,
non-overlapping file or directory ownership. Sequential work, shared state, and
cross-task decisions remain on root. Strategy and profiles guide the decision;
they do not force delegation.

## First-use setup

```toml
[subagents]
# TAPL asks for preferences on the first concrete request.
setup_complete = false
enabled = true
# strategy is a decision bias; the agent still evaluates each task.
strategy = "aggressive"
preference = ""

[subagents.models]
# Models are recorded from the current runtime during first-use setup.
```

On the first concrete TAPL request, the agent checks the model IDs and reasoning
efforts exposed by its current runtime, then asks whether to use SubAgents and
what preferences to apply. It saves the answer in the resolved
configuration file and marks setup complete. TAPL never calls a provider API or
ships an external model list for this step. `enabled = true` takes effect only
after setup is complete. If the runtime catalog is unavailable, setup remains
pending and work stays on the root agent. After an answer, the agent records it
with `tapl_configure_subagents`; the answer itself is the user confirmation.
Existing configurations with an explicit model allowlist or `enabled = false`
remain complete and retain their choices; new model settings apply only when
the user requests an update.

After your answer, TAPL also records the full runtime catalog in `subagents.available_models`.
Ordinary `tapl_get_next` entry omits catalog arguments and uses saved preferences.
It does not check for new models at the start of each session. Before delegating,
verify the selected model/effort against the live tool and allowlist; skip
unavailable pairs and use root if none remain. Saved catalog entries are not
proof that a model is still available.

Only during setup or a user-requested settings check, compare the entire live
catalog with `tapl_get_next(available_models=..., catalog_complete=true)`, including
models fixed by agent roles as well as selectable overrides. When a catalog is
supplied without explicit completeness, the response reports `comparison_status="incomplete"` with no
inferred changes or configuration prompt; continue work without a repair query.
A complete comparison reports `"compared"`, or `"no_baseline"` for legacy settings.
A complete empty catalog can establish removal, while a partial or omitted one
cannot. Confirmed additions, removals and effort changes offer update or keep.
Wait for the user's answer before saving through `tapl_configure_subagents`.
Keeping records the confirmed catalog without changing the allowlist. Existing
configurations without a catalog remain usable; record a baseline during settings review.

## Profiles and model selection

The installed template includes these model-neutral advisory profiles, listed
in safety-first order:

| Profile | Use when | Bias |
| --- | --- | --- |
| `high-risk-cross-cutting` | High-risk, cross-cutting, shared-context, or coordination-heavy work | `avoid` |
| `deep-reasoning` | Complex, uncertain, or context-heavy decisions | `neutral` |
| `general-implementation` | Ordinary bounded implementation work | `inherit` |
| `bounded-routine` | Small, local, predictable, low-risk work | `prefer` |

`inherit` follows the global strategy, `prefer` favors delegation, `neutral` adds no directional preference, and `avoid` favors root. These remain advisory biases.

Profiles have empty candidates until setup supplies the runtime-supported model
and effort pairs. They describe task characteristics and delegation bias; they
do not assign permanent roles to model IDs.

An explicit `profiles = []` disables profiles. Any non-empty user
`subagents.profiles` array fully replaces the template profiles, and its
candidates must be present in `subagents.models`.

When enabled, TAPL delivers its delegation policy, active profiles, and
model/reasoning allowlist through `tapl_get_next`. Matching remains advisory: the
agent evaluates all task characteristics, prefers the most specific profile,
and uses configured order only as a tie-break. It may choose and record a
justified profile or candidate override, skips unavailable candidates, and
falls back to another allowlisted pair or root when needed. The installed
`.tapl/config.toml` records selected models and preferences, then documents
every runtime option, its type, and allowed values inline.

For example, this array replaces the template profiles with one model-neutral
preference:

```toml
[[subagents.profiles]]
name = "release-automation"
characteristics = "bounded deployment steps with a known rollback"
delegation_bias = "prefer"
candidates = []
```

## Strategy and execution boundaries

The `strategy` setting controls the delegation bias:

- `aggressive` (the default) favors delegation when tasks are independent,
  sufficiently self-contained, low enough risk, and have meaningful parallel
  value or save root context. It does not require delegation when context sharing
  or coordination cost makes root execution better.
- `balanced` weighs the same dimensions without a directional preference.
- `conservative` favors root execution and delegates only when the expected
  parallel value or root context savings clearly outweigh context transfer,
  coordination, and risk.

A parallel batch uses tasks with the same PLAN and `parallel_group`, `execution_mode="parallel"` and `executor_kind="subagent"`, started atomically with `tapl_dispatch_tasks`. Root verifies each `SubAgent Model` record and manifest before spawning one SubAgent per execution within its owned paths, then completes, blocks or skips it with the exact returned `execution_id`. Recover or cancel an interrupted batch or spawn failure before retrying; do not leave a partial batch and start another around it.

For stored or executable tasks, every strategy still requires execution approval,
dependency readiness, exclusive non-overlapping `owned_paths`, atomic dispatch,
and settlement by the exact `execution_id`; the root retains TAPL writes and
cross-task decisions. Dispatch records the manifest model and reasoning effort
in the legacy `SubAgent Model`
custom field before the runtime spawns that SubAgent. To change the bias, set
`strategy` to `balanced` or `conservative`; to disable TAPL delegation guidance,
set `enabled = false`. This does not remove delegation instructions from another
source such as `AGENTS.md`.

With `workflow.authoring_detail = "precise"`, executable-task decisions use these canonical custom fields throughout the lifecycle:

- `Task Profile` records the selected profile (or no match) and match reason.
- `Task Characteristics` records independence, required context, risk,
  coordination cost, and parallel value.
- `Execution Decision` records root versus SubAgent, model/effort, rationale,
  and any profile or model override. Create or update these fields during task
  design, before dispatch, and after settlement when the decision changes.
- `User Notes` is conditional. Add it only for durable user-relevant facts not
  represented by standard fields, using concise category/content/impact entries.

With `normal` or `minimal`, routine root work can omit advisory filler. Model selection or profile overrides still retain `Task Profile`, relevant `Task Characteristics`, and `Execution Decision`, with the model, effort and rationale; explain overrides. See [Authoring detail](authoring-detail.md).

The legacy `SubAgent Model` field remains written at atomic dispatch for
compatibility and is omitted when no SubAgent runs. The installed configuration
is preference input; runtime support, safety gates, and the recorded decision
remain authoritative.

The workflow follows the scope the user authorized. An explicit request to edit
or test counts as approval for that work; an investigation-only request does not
authorize a fix. Record the applicable approval and execution state without
asking again for permission already given.

## Read-only exploration

Once setup is complete and delegation is enabled, bounded exploration may use a
host SubAgent before or after planning without artificial tasks, batches, or
`owned_paths`. Skip scouting for self-contained requests or sufficiently known
scope. Root handles a known target needing one check; unclear targets,
dependencies, or validation boundaries can use one eligible read-only helper
without nested helpers.

Before classification, root and helper share at most three targeted local
read-only lookups total. Failures do not replenish that budget; unreported helper
usage consumes its allocated quota. Give the helper the request, scope, remaining
lookup and response budgets, restrictions, and stop condition instead of full
history by default. Prioritize source, configuration, and tests; request compact
`file:line` findings, dependencies, validation needs, risks, unknowns, and lookup
usage. Root uses the report without repeating searches except for essential
unresolved questions within the remaining budget.

Before classification, neither root nor scout may edit, run tests, perform external research or history searches, or mutate TAPL state. Root classifies the workflow and writes its records after
the scout. After classification, applicable source and history rules apply.
Select only model/effort pairs in both the configured allowlist and live runtime
catalog. Pending setup, disabled delegation, or no suitable candidate leaves the
lookup on root. Scouting does not bypass execution approval and does not
promise lower latency or token usage.

## Inspect and change settings

```sh
taplctl config get subagents --json
taplctl config set subagents.strategy balanced
taplctl config set subagents.enabled false
```

Inspect `setup_complete`, the model allowlist and the recorded decision when delegation does not occur. Disabling guidance leaves other sources of delegation authorization in effect. TAPL coordinates database execution state; it does not itself launch workers or terminate an external worker process during batch recovery.

## Related pages

[Configuration](configuration.md) · [Authoring detail](authoring-detail.md) · [Workflow](../concepts/workflow.md) · [MCP tools](../reference/mcp.md)
