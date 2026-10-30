# MCP tool reference

[Documentation](../README.md) · [한국어](mcp.ko.md)

`tapl-mcp` exposes the workflow application over MCP stdio. Management commands belong to [the CLI](cli.md). This page covers all **30 public tools** registered by [`mcp_server.py`](../../tapl/taplctl/mcp_server.py); the connected server's JSON schema is the authority for exact validation.

## Common contract

Pass the current Codex hook **`session_id` on every call**, including reads. Most schemas make it optional for compatibility, but omission selects the isolated legacy namespace (`""`), not another session's active RUN. Identity is at most 256 characters without surrounding whitespace or control characters. `tapl_discard_run` requires an explicit owner, including `""` for a legacy RUN.

Tool responses are structured objects. In code mode, discover the needed tools together by exact name without printing the full tool catalog. Emit `structuredContent` once, falling back to parsed text when necessary; do not print both envelope copies. Write receipts include current recommendations and compact validation. All blocking errors are retained; omitted warnings are counted in `omitted_issue_count`.

Runtime status, entry, context, validation and applicable write receipts expose `authoring_policy={configured,effective,workflow_mode}` for the selected session. `config.workflow.authoring_detail` keeps the configured value, including the default `auto`. Automatic detail maps Fast → `minimal`, Standard → `normal`, Strict → `precise`, falling back to `normal` with `workflow_mode=null` when no RUN is active. Explicit levels remain fixed. See [Authoring detail](../guides/authoring-detail.md).

PLAN IDs match `PLAN-001` or legacy `SPEC-001` with at least three digits; TASK IDs match `TASK-001` with at least three digits. A task's `spec_id` identifies its topic's existing plan. Send structured plan/task fields; the application merges them and renders Markdown. Omitted plan fields are preserved.

`custom_fields` is a JSON object for durable searchable metadata. Preserve key names and value types. Existing keys merge; a top-level `null` value deletes that key. With effective `precise` authoring (explicit or `auto` in Strict mode), every executable task uses the canonical objects below. `normal` and `minimal` allow ordinary root work to omit advisory filler, while retaining selection metadata for model choices or profile overrides and durable facts absent from standard fields:

```json
{
  "Task Profile": {"name": "none", "match_reason": "No advisory profile applies."},
  "Task Characteristics": {
    "independence": "One owned documentation file.",
    "context": "Current CLI help.",
    "risk": "Low; reversible text change.",
    "coordination_cost": "Small.",
    "parallel_value": "No useful concurrent edit."
  },
  "Execution Decision": {
    "executor": "main",
    "delegation_reason": "A bounded edit stays on the main agent.",
    "override": false
  }
}
```

When choosing a model, add `model`, `reasoning_effort`, and `model_reason` to `Execution Decision`. Dispatch records the legacy `SubAgent Model` before returning the manifest. Readable metadata is part of the record; avoid compressed prose. See [Records](../concepts/records.md) and [SubAgents](../guides/subagents.md).

## Entry, inspection, and setup

`session_id` is common and omitted from the tables except where required.

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_get_next` | None | `known_policy_revision`; `available_models`, `catalog_complete=false` for explicit setup/settings checks. Returns policy, config, state summary, and next actions. |
| `tapl_get_status` | None | `full=false`, `include_events=false`, `events_limit=12` (0–100). Details for inspection/resume/recovery; `full=true` includes record bodies. |
| `tapl_validate_state` | None | Validates plan detail, task contracts, dependencies, execution order, and approval. |
| `tapl_get_context` | None | `event="Manual"` selects lifecycle guidance. |
| `tapl_configure_subagents` | `user_confirmed`, `enabled`, `strategy`, `models`, `available_models` | `preference=""`, `profiles`. Saves confirmed setup to the effective config path. `strategy`: `conservative`, `balanced`, `aggressive`. |

MCP initialization delivers a short entry gate. Before non-trivial or uncertain work, call `tapl_get_next` **once** and retain its complete `workflow_policy`, `subagent_guidance`, and `config`. SessionStart bootstrap and hook entry share that call. Ordinary entry omits model catalog arguments. `state_summary` includes RUN identity/classification, record presence, task/queue/batch counts, and execution approval. Use `tapl_get_status` only for missing details or an inspection recommendation.

A `policy_revision` covers the exact policy, guidance, config and `authoring_policy`, so RUN mode changes invalidate the old bundle. Send `known_policy_revision` only while the complete policy, guidance and config for that revision remain in current context. A new revision returned in a write receipt alone does not mean its full policy was loaded. A matching revision omits unchanged policy fields but still returns fresh state/recommendations and requested complete catalog comparisons. Unknown revisions or changed content return full policy. Omit it in a new session, after compaction, or whenever retention is uncertain. It is neither a state cache nor approval evidence.

For a user-requested settings comparison, supply the **complete live delegation-tool catalog**, including fixed-role models, and `catalog_complete=true`. A verified empty catalog can establish removal. Default `false` treats any supplied catalog as incomplete (`comparison_status="incomplete"`), infers no changes, and does not request reconfiguration. Never fill missing live entries from saved settings. Setup confirmation must be a real user answer or exact requested change; timeout is not confirmation. Models must be exposed by the current delegation tool, not inferred from a provider API catalog. Empty `models` is allowed only when disabled; `profiles=[]` disables advisory profiles.

When a RUN summary, split, archive or other RUN transition changes mode or effective detail, its receipt preserves `policy_refresh_required=true`, `authoring_policy` and a highest-priority `tapl_get_next` recommendation. Refresh policy, then supplement the current PLAN and unfinished TASK evidence for the new rigor. Completed/archived records are not automatically rewritten. Required evidence and Strict typed-field warnings are described in [Authoring detail](../guides/authoring-detail.md#selection-example-and-verification).

State validation uses one transactionally consistent snapshot. Reuse successful write recommendations directly: writes, read-only status checks, and Stop hooks do not require another entry call. Refresh after failure/truncation, policy/context loss, or possible workflow changes by another actor.

## History and memory

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_search_history` | `query` (1–500 characters) | `limit` (1–50; configuration default when omitted). Searches active/archived originals. |
| `tapl_get_item` | `item_id` (positive integer) | `compact=false`. Reads a plan/task/finding. Compact mode omits generated body only when exactly reconstructible from canonical fields; custom/raw bodies and findings remain intact. |
| `tapl_list_archives` | None | `limit` (1–100). Lists recent archives. |
| `tapl_get_archive` | `archive_id` | Numeric ID as a string or stable slug; returns items and events. |
| `tapl_recall` | None | `query=""` (at most 500 characters), `limit=3` (1–50), `offset=0` (nonnegative). Empty query lists memories. No capture/reinforcement. |
| `tapl_get_memory` | `memory_id` | Returns memory and original source; missing/deleted memory returns null. |
| `tapl_update_memory` | `memory_id`, `expected_revision` (positive integer) | `note` (1–240 characters), `cue` (3–5 entries), `state` (`active` or `superseded`). Explicit user request only. |
| `tapl_delete_memory` | `memory_id`, `expected_revision` (positive integer) | Explicit user request only; tombstones the memory so recall/reinforcement cannot use it. |

Check original evidence from `tapl_get_item` or `tapl_get_archive` before using a recalled hint. Revision conflicts require fresh review before retrying memory edits. `recall.enabled=false` disables automatic recall/capture/review/reinforcement; manual inspection remains available. See [Associative memory](../guides/memory.md) for ranking and maintenance.

## RUNs, plans, findings, and approval

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_summarize_run` | `summary` (1–2000 characters), `work_type`, `workflow_mode` | `recall_query` (at most 500 characters), one automatic recall per RUN. |
| `tapl_split_run` | `requests` (2–20 objects) | Each object has `key`, `summary`, `work_type`, `workflow_mode`, optional `depends_on=[]` referencing earlier keys. For explicitly separate RUN lifecycles before planning. |
| `tapl_apply_plan` | None in schema | `plan_id="PLAN-001"`, `title`, `summary`, `objective`, `requirements_trace`, `selected_approach`, `affected_files`, `execution_order`, `risks`, `validation`, `approval_needs`, `notes`, `custom_fields`, `status`. Workflow validation still requires an adequate plan. |
| `tapl_add_finding` | `title` | `source=""`, `finding=""`, `impact=""`, `related_ids=""`. Record decision-relevant evidence and source. |
| `tapl_approve_execution` | `prompt` | `source="explicit_user"` or `"request_user_input"`. Only records actual execution authorization. |
| `tapl_reject_execution` | `prompt` | Same `source` values; preserves the explicit rejection. |
| `tapl_finish_run` | `result` | `expected_run_id`, `memory_candidates`, `memory_uses`, `memory_review`; see completion below. |
| `tapl_finish_archive` | `slug` (1–120 characters) | `summary=""` (at most 2000 characters). After task/batch settlement and completion review. |
| `tapl_discard_run` | `run_id`, `confirmed`, `confirmation_run_id`, `session_id` | All required; see confirmed discard below. |

`work_type`: `answer`, `investigation`, `analysis`, `planning`, `implementation`, `mixed`. `workflow_mode`: `fast`, `standard`, `strict`. TAPL derives `record_mode`; only Fast non-durable answer/investigation/analysis/planning can be lightweight. Durable or Standard/Strict work uses plans/tasks. Different topics normally receive distinct PLANs in one RUN, not separate RUNs.

`tapl_split_run` keys are 1–100 characters, start with an alphanumeric character, and then allow letters, digits, `.`, `_`, or `-`. Forward dependencies are not accepted. Keep all requirements for one outcome in the same topic plan.

## Tasks and parallel batches

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_create_task` | `task_id`, `title`, `spec_id`, `goal`, `action`, `verification` | `execution_mode="sequential"`, `executor_kind="main"`, `parallel_group`, `owned_paths`, `depends_on`, `custom_fields`. Creates Pending work. |
| `tapl_start_task` | `task_id` | `custom_fields`. Starts dependency-ready sequential work. |
| `tapl_dispatch_tasks` | `task_ids` (at least two) | `batch_id`, `failure_policy="continue"`, `execution_metadata`. Atomic parallel dispatch; returns execution manifest. |
| `tapl_complete_task` | `task_id`, `verification`, `result` | `execution_id`, `custom_fields`. Complete after implementation and verification. |
| `tapl_block_task` | `task_id`, `blocker`, `next_action` | `execution_id`, `verification`, `custom_fields`. Preserves concrete blocker and next action. |
| `tapl_skip_task` | `task_id`, `result` | `execution_id`, `custom_fields`. Records intentional omission reason. |
| `tapl_cancel_batch` | `batch_id`, `reason` | `block_tasks=true`; false returns tasks to Pending. Cancels active executions. |
| `tapl_recover_batch` | `batch_id`, `reason` | Returns interrupted active tasks to Pending for safe retry. |

Parallel tasks require `execution_mode="parallel"`, `executor_kind="subagent"`, the same plan and nonempty `parallel_group`, completed dependencies, exclusive non-overlapping `owned_paths`, and execution approval. Root dispatches atomically, checks each stored `SubAgent Model`, then spawns actual agents. `execution_metadata` maps task IDs to runtime selection objects, including a complete `model`/`reasoning_effort` pair and rationale when selected. Root alone writes TAPL state and settles each task with its exact manifest **`execution_id`**. On interruption/spawn failure, recover or cancel the batch before retrying. A stable `batch_id` supports idempotent retry for the same RUN/task set; it is not a way to reuse a different batch.

## Sequential lifecycle example

The following is an ordered MCP call outline with `precise` explicitly selected using `taplctl config set workflow.authoring_detail precise`, not a shell command or a script to run blindly. `call(name, arguments)` means your host's MCP invocation. Replace `sid` with the actual hook identity. Load policy, inspect relevant history, and obtain the user's plan confirmation before finalizing a plan. Record approval only if execution was actually authorized. Use concrete evidence for completion fields.

```javascript
const sid = "<hook session_id>";
const call = (name, args) => host.callTool(name, { ...args, session_id: sid });
await call("tapl_get_next", {});
const run = await call("tapl_summarize_run", {
  summary: "Correct an outdated CLI example and verify the documentation.",
  work_type: "implementation", workflow_mode: "standard"
});
// Refresh the complete policy when the classification receipt requests it.
if (run.policy_refresh_required) await call("tapl_get_next", {});
await call("tapl_search_history", { query: "CLI documentation example" });
// After the user confirms the plan:
await call("tapl_apply_plan", {
  plan_id: "PLAN-001", title: "Correct CLI documentation", status: "Finalized",
  summary: "Align the example with current command help.",
  objective: "Readers can run the documented command.",
  requirements_trace: "REQ-001: Current command and matching translations.",
  selected_approach: "Edit the topic's English and Korean examples.",
  affected_files: "docs/reference/cli.md; docs/reference/cli.ko.md",
  execution_order: "TASK-001 edit; TASK-002 verify.",
  risks: "A copied example could become stale.",
  validation: "Compare command help, translations, links and git diff --check.",
  approval_needs: "Explicit user authorization before repository edits."
});
// Explicit precise authoring: include the canonical custom_fields on each executable task.
await call("tapl_create_task", {
  task_id: "TASK-001", title: "Update the examples", spec_id: "PLAN-001",
  goal: "Use current CLI arguments.", action: "Edit both language examples.",
  verification: "Compare both examples with command help.", custom_fields: metadata
});
await call("tapl_create_task", {
  task_id: "TASK-002", title: "Verify documentation", spec_id: "PLAN-001",
  goal: "Confirm consistent public guidance.", action: "Check links and language parity.",
  verification: "Run link checks and git diff --check.",
  depends_on: ["TASK-001"], custom_fields: metadata
});
// Only after a real execution instruction or confirmation:
await call("tapl_approve_execution", {
  source: "explicit_user", prompt: "Update and verify the CLI examples."
});
await call("tapl_start_task", { task_id: "TASK-001" });
// Perform the authorized edits and verify them before completing:
await call("tapl_complete_task", {
  task_id: "TASK-001", verification: "Both examples match current CLI help.",
  result: "Updated the English and Korean command examples."
});
await call("tapl_start_task", { task_id: "TASK-002" });
// Perform the declared checks before completing:
await call("tapl_complete_task", {
  task_id: "TASK-002", verification: "Links and language parity checked; diff check passed.",
  result: "Documentation validation passed."
});
await call("tapl_finish_run", {
  result: "Examples updated and verified.", expected_run_id: run.active_run.id,
  memory_review: { decision: "skip", reason: "No recurring lesson beyond the source documentation." }
});
// Inspect the returned memory review; resolve outstanding failures first.
await call("tapl_finish_archive", {
  slug: "2026-10-30-cli-example", summary: "CLI examples aligned and verified."
});
```

`metadata` denotes the canonical object above; `host` denotes your MCP client adapter, which returns the parsed structured tool result. These names are explanatory, not exported TAPL APIs. After writes, use receipt recommendations without routine status/entry polling. Use `tapl_validate_state` when validation details are needed. Planning-only work remains active until the user explicitly chooses to finish/archive.

## Completion and memory arguments

`tapl_finish_run` saves the verified result before a separate archive call. All actionable tasks and active batches must be settled. With any memory arguments, `expected_run_id` must identify the active RUN.

- `memory_candidates`: at most two objects. Each has `slot` (1 or 2), `cue` (3–5 distinct entries), `note` (1–240 characters), `source_run_id`, optional positive `source_item_id`, and optional `replaces_memory_id`. Capture only verified lessons with recurring cues that reduce future exploration. Candidates imply capture.
- `memory_uses`: at most 50 objects with `memory_id`, positive `revision`, Boolean `source_checked`, and `usage` (1–500 characters). Include only actual use after original-source verification.
- `memory_review`: `{ "decision": "capture" | "skip", "reason": "..." }`; skip requires a reason of 1–240 characters. Omitting both candidates and review leaves `review_required` when review applies.

Capture failures preserve the work result. Inspect the receipt, retry failed slots once with corrected input, then explicitly skip unresolved failures with a reason before archiving. See [Associative memory](../guides/memory.md).

<a id="confirmed-discard"></a>

## Confirmed discard

`tapl_discard_run` requires literal `confirmed=true` and `confirmation_run_id` exactly matching the full selected `run_id`, including case and whitespace. The owner session is mandatory. It processes the selected RUN and all queued RUNs with the same owner and split group, regardless of dependency links. Each RUN is deleted if truly empty or force-archived if it has retained work. Active database executions/batches are cancelled, and no other RUN starts. It does not terminate external agent processes. This is the explicit Viewer close action, not the normal finish/archive route; see [Viewer](../guides/viewer.md#discard-a-run).

## Availability and verification

The current server registers every tool listed above. Optional semantic dependencies affect search execution, not tool registration. `searchd` is Unix-only. Disabled automatic recall does not remove manual memory inspection. Memory mutation still requires an explicit user request and current revision. Viewer clients use advertised `associativeMemory` and `discardRun` capabilities so older servers keep supported views available.

Schema/session/lifecycle behavior is covered by `test_mcp_native.py`, `test_session_mcp.py`, `test_application.py`, `test_context_optimization.py`, and the memory/discard suites in `tapl/tests`. See [Architecture](../development/architecture.md), [Contributing](../development/contributing.md), and [Workflow](../concepts/workflow.md).
