# MCP tool reference

[Documentation](../README.md) · [한국어](mcp.ko.md)

`tapl-mcp` exposes the workflow application over MCP stdio. This page covers the **37 agent tools** and the separate [Viewer stdio tools](#viewer-stdio) registered by [`mcp_server.py`](../../tapl/taplctl/mcp_server.py). The connected server's JSON schema is the authority for exact validation. Management commands belong to [the CLI](cli.md).

Claude Code requires the exact `claude-code:<native-session-id>` hook owner on every call, even reads. Its missing/raw/foreign-client IDs are rejected; the legacy omission behavior below applies only to Codex. Approval source `request_user_input` remains the stable tool-confirmed provenance value, including Claude `AskUserQuestion` answers. Host-specific policy and model setup are described in the [Claude guide](../getting-started/claude-code.md).

## Common contract

On an agent connection, pass the current host hook **`session_id` on every call**, including reads. Most schemas make it optional for compatibility. Codex alone permits omission and selects the isolated legacy namespace (`""`) in that case. Claude Code requires its exact namespaced owner. Identity is at most 256 characters without surrounding whitespace or control characters. `tapl_discard_run` requires an explicit owner, including `""` for a legacy RUN.

Tool responses are structured objects. When the host provides code mode, discover the needed tools together by exact name without printing the full tool catalog. Emit `structuredContent` once, falling back to parsed text when necessary; do not print both envelope copies. Write receipts include current recommendations and compact validation. All blocking errors are retained; omitted warnings are counted in `omitted_issue_count`.

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

`session_id` is common and omitted from the tables except where schema-required; it remains mandatory on every Claude Code call.

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_get_next` | None | `known_policy_revision`; `available_models`, `catalog_complete=false` for explicit setup/settings checks. Returns policy, execution settings, state summary, and next actions. |
| `tapl_get_status` | None | Optional `source_db` (exact source filename; omission selects local). `full=false`, `include_events=false`, `events_limit=12` (0–100). Details for inspection/resume/recovery; `full=true` includes record bodies. |
| `tapl_validate_state` | None | Validates plan detail, task contracts, dependencies, execution order, and approval. |
| `tapl_get_context` | None | `event="Manual"` selects lifecycle guidance. |
| `tapl_configure_subagents` | `user_confirmed`, `enabled`, `strategy`, `models`, `available_models` | `preference=""`, `profiles`. Saves confirmed settings to the effective config path; the agent supplies an [English preference summary](../guides/subagents.md#first-use-setup). `strategy`: `conservative`, `balanced`, `aggressive`. |

MCP initialization delivers a short entry gate. Before non-trivial or uncertain work, call `tapl_get_next` **once** and retain its complete `workflow_policy`, `subagent_guidance`, and `config`. SessionStart bootstrap and hook entry share that call. Ordinary entry omits model catalog arguments. `state_summary` includes RUN identity/classification, record presence, task/queue/batch counts, and execution approval. Use `tapl_get_status` only for missing details or an inspection recommendation.

`config` contains the settings needed for current execution: source path/existence, applicable client identity, `workflow.authoring_detail`, `recall.enabled`, and the active SubAgent setup/enable state. Completed, enabled delegation also includes the approved preference, strategy, model/effort allowlist, profiles and applicable Claude selection semantics. Disabled or pending delegation returns only the flags, identity and guidance needed for that state. The saved `available_models` catalog, search settings and Viewer settings are omitted. Actual selections and preferences appear once in structured settings; policy and guidance supply the common rules and procedures. There is no config-detail option. Use [user settings](#user-settings), `taplctl config get`, or `taplctl doctor` for full administrative settings.

A `policy_revision` covers the exact delivered policy, guidance, execution settings and `authoring_policy`. Changes to that bundle, including RUN mode, invalidate its revision; unrelated search, Viewer or saved-catalog-only changes do not while the delivered source path/existence and client identity stay the same. Send `known_policy_revision` only while the complete bundle for that revision remains in current context. A new revision returned in a write receipt alone does not mean its full policy was loaded. A matching revision omits unchanged policy fields but still returns fresh state/recommendations and requested catalog comparisons. A complete comparison that finds model changes resends the current bundle with the delta so preference review is self-contained. Unknown revisions or changed content return the full execution-policy bundle. A recorded Codex `PostCompact` event invalidates the previous revision for that session. Omit the revision in a new session, after compaction, or whenever retention is uncertain. It is neither a state cache nor approval evidence.

For a user-requested settings comparison, supply the **complete live delegation-tool catalog**, including fixed-role models, and `catalog_complete=true`. A verified empty catalog can establish removal. Default `false` treats any supplied catalog as incomplete (`comparison_status="incomplete"`), infers no changes, and does not request reconfiguration. Never fill missing live entries from saved settings. Setup confirmation must be a real user answer or exact requested change; timeout is not confirmation. Models must be exposed by the current delegation tool, not inferred from a provider API catalog. Claude Code also supports a confirmed `models={inherit: []}` selection, which is excluded from `available_models`; an alias with `[]` leaves effort unspecified. See [Claude model selection](../getting-started/claude-code.md#models-and-agent-execution). Empty `models` is allowed only when disabled; `profiles=[]` disables advisory profiles.

`model_changes` has `baseline_recorded`, `comparison_status`, `changed` and `changes`. Each entry in `changes` is `{model, before, after}` with actual effort arrays; `null` means the model is absent on that side, while `[]` retains Claude's unspecified-effort meaning. Incomplete input produces no inferred changes. A complete legacy catalog without a saved baseline reports `"no_baseline"` without treating the current catalog as additions. See [SubAgent setup](../guides/subagents.md#first-use-setup) for update/keep confirmation.

A successful `tapl_configure_subagents` receipt returns the full confirmed `subagents` configuration, including its saved catalog, plus immediately applicable current guidance. It does not require another entry read solely to use the confirmed settings.

When a RUN summary, split, archive or other RUN transition changes mode or effective detail, its receipt preserves `policy_refresh_required=true`, `authoring_policy` and a highest-priority `tapl_get_next` recommendation. Refresh policy, then supplement the current PLAN and unfinished TASK evidence for the new rigor. Completed/archived records are not automatically rewritten. Required evidence and Strict typed-field warnings are described in [Authoring detail](../guides/authoring-detail.md#selection-example-and-verification).

State validation uses one transactionally consistent snapshot. Reuse successful write recommendations directly: writes, read-only status checks, and Stop hooks do not require another entry call. Refresh after failure/truncation, policy/context loss, or possible workflow changes by another actor.

## User settings

`tapl_get_settings` reads the current workspace's effective configuration path, editable field schema, values, defaults, stored overrides and revision. It does not initialize or mutate a workflow database.

`tapl_save_settings` requires `values` (an object keyed by canonical editable field names) and `expected_revision` from that document. Use it only for changes the user explicitly requested. Model maps and profiles are structured values and validate together before one atomic write. Optional `reset_all=true` requires `values={}` and an explicitly confirmed reset; it removes all supported Codex/Claude overrides while retaining unrelated content and catalogs. Stale revisions fail without overwriting changes. Do not automatically retry a save after a lost acknowledgement; reload first. There is no arbitrary file-path argument. Both tools retain the common client/session identity rules and operate independently of selected RUN/source ownership. See [Viewer settings](../guides/configuration.md#viewer-settings).

A save or reset that changes settings can trigger background writes to the current workspace's semantic index. The optional `reindex` field reports `status="scheduled"` when the background check is scheduled or `status="failed"` with an `error` if scheduling fails. Check the index itself with `taplctl reindex --dry-run --json`. See [Search indexing](../guides/search.md#semantic-dependencies-and-index).

## History and memory

Search, lists, and recall read multiple databases in the working folder. Preserve each result's `source_db` in detail reads and `memory_uses`. Foreign updates, deletion, and RUN discard are rejected; foreign memory uses return a read-only skip. A memory use must name its source when the same ID exists in another database. Per-source failures appear in `source_errors`. See [Local identity and shared history](../guides/storage.md).

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_get_run` | `run_id` (1–256 characters) | Optional `source_db`. Reads the exact active/archived RUN, items, task counts and execution metadata; does not follow its owner's newer RUN. Includes `readonly` and source provenance. |
| `tapl_list_records` | None | `query=""` (0–500 characters), `scope="all"` or `"run"`, optional `run_id`, `source_db`, `offset=0` (0–1,000,000), `limit=50` (1–50). Run scope requires an exact RUN ID; all scope federates sources. Returns literal title/body/stable-ID matches, full filtered totals, per-RUN counts and source errors. |
| `tapl_search_history` | `query` (1–500 characters) | `limit` (1–50; configuration default when omitted). Searches active/archived originals. |
| `tapl_get_item` | `item_id` (positive integer) | Optional `source_db` (exact source filename; omission selects local). `compact=false`. Reads a plan/task/finding. Compact mode omits generated body only when exactly reconstructible from canonical fields; custom/raw bodies and findings remain intact. |
| `tapl_list_archives` | None | `limit` (1–100). Lists recent archives. |
| `tapl_get_archive` | `archive_id` | Optional `source_db` (exact source filename; omission selects local). Numeric ID as a string or stable slug; returns items and events. |
| `tapl_recall` | None | `query=""` (at most 500 characters), `limit=3` (1–50), `offset=0` (nonnegative). Empty query lists memories. No capture/reinforcement. |
| `tapl_list_memory_cues` | None | `query=""` (at most 200 characters), `limit=20` (1–50), `offset=0` (nonnegative), optional exact `source_db`. Read-only labels and usage counts; defaults to the local writing DB. Reuse matching labels before capture/cue edits. |
| `tapl_merge_memory_cues` | `target_cue` (existing label, 1–80 characters), `cues` (1–20 existing labels to absorb, each 1–80 characters) | Optional exact `source_db` (omission selects local). Merges catalog definitions/links only in the local writing DB and retains old labels as aliases. Alias inputs resolve to representatives; foreign sources are rejected. Preserves memory content/indexes; repeated calls are idempotent. |
| `tapl_get_memory` | `memory_id` | Optional `source_db` (exact source filename; omission selects local). Returns memory and original source; missing/deleted memory returns null. |
| `tapl_use_references` | `expected_run_id`, `references`, `session_id` | Records actual use during this RUN from originals already opened in this exact conversation. Batch 1–50; each entry has source-qualified identity and trimmed `usage` (1–500 characters). Atomic, idempotent, and independent of memory reinforcement. |
| `tapl_update_memory` | `memory_id`, `expected_revision` (positive integer) | Optional `source_db` (exact source filename; omission selects local). `note` (1–240 characters), `cue` (3–5 entries), `state` (`active` or `superseded`). Explicit user request only. |
| `tapl_delete_memory` | `memory_id`, `expected_revision` (positive integer) | Optional `source_db` (exact source filename; omission selects local). Explicit user request only; tombstones the memory so recall/reinforcement cannot use it. |

Catalog lookup also searches aliases but returns only representative labels and
`usage_count`, without an aliases array. Counts include each nondeleted memory
once per representative. After establishing equivalence from inspected labels,
the agent may use `tapl_merge_memory_cues` during capture/cue selection without
per-merge user confirmation. TAPL does not merge by fuzzy similarity. The response
has `target_cue`, `merged_cues`, `affected_memories`, and
`status="merged"|"unchanged"`. Later capture/cue edits resolve aliases to
representatives and reject duplicates or fewer than three unique cues. See
[Reuse cue labels when storing](../guides/memory.md#reuse-cue-labels-when-storing)
for merge scope and an example.

Automatic recall from `tapl_summarize_run` has one final 3,600 UTF-8 byte cap
for its full `recall` object, including status, diagnostics, and source errors.
Compact hints keep the full note and exact source pointers; fewer than three may
fit or qualify. This does not change manual recall/detail fields, pagination, or
Viewer responses. Query boundaries, candidate limits, and diagnostics are described
in [Recall criteria and limits](../guides/memory.md#recall-criteria-and-limits).

Successful agent lookups may record compact pointers in the existing owned RUN for its mindmap. This does not capture/reinforce memory or write foreign history; Viewer reads are not tracked. See [Agent lookup traces](../guides/memory.md#agent-lookup-traces).

For `tapl_use_references`, `session_id` is explicitly required; blank or omitted legacy identity is unsupported. Every entry requires `kind`, exact `source_db` filename and `usage`, plus exactly one target shape: `kind="memory", target_type="memory", memory_id`; `kind="history", target_type="item", item_id` (positive integer); or `kind="history", target_type="run", run_id`. String IDs and source names are 1–256 characters. Unknown fields are rejected. Titles and source pointers come from recorded returned memory notes/details and opened originals, not caller-supplied metadata. A complete recall note qualifies without another memory-detail fetch; its exact original still needs an opened-read record.

Replace the example IDs and `source_db` with the exact values returned by earlier original reads in the same hook session:

```json
{
  "expected_run_id": "current-run-id",
  "session_id": "current-hook-session-id",
  "references": [
    {
      "kind": "history",
      "source_db": "tapl-source.db",
      "target_type": "item",
      "item_id": 123,
      "usage": "Used the verified rollback constraint to choose this implementation."
    },
    {
      "kind": "memory",
      "source_db": "tapl-source.db",
      "target_type": "memory",
      "memory_id": "memory-id",
      "usage": "Applied the checked indexing lesson."
    }
  ]
}
```

The entire batch is validated before writing. Responses contain compact `outcomes` with input `index` and `status="recorded"|"unchanged"`, plus `counts`; repeated identities preserve the first usage reason. A memory's matching original is included without duplicating an existing card or edge. The 200-used-identity limit includes these originals. Diagnostics include `invalid_reference`, `session_required`, `stale_run`, `invalid_proof` and `reference_limit`; schema errors can be rejected before application handling. Missing or discarded proof requires fetching the missing note or original, not an invented usage claim. Unrelated old lookups are never imported.

Check original evidence from `tapl_get_item` or `tapl_get_archive` before using a recalled hint. Revision conflicts require fresh review before retrying memory edits. `recall.enabled=false` disables automatic recall/capture/review/reinforcement; manual inspection remains available. See [Associative memory](../guides/memory.md) for ranking and maintenance.

## RUNs, plans, findings, and approval

A successful `tapl_summarize_run` returns `viewer_url` for the classification notice. Use that URL unchanged for the [local Viewer link](../guides/viewer.md#open-a-workspace).

| Tool | Required arguments | Optional arguments and behavior |
| --- | --- | --- |
| `tapl_summarize_run` | `summary` (1–2000 characters), `work_type`, `workflow_mode` | `recall_query` (at most 500 characters; prefer 3–8 core terms). Omission or empty uses the first eight summary tokens. At most three relevant automatic hints once per RUN. |
| `tapl_split_run` | `requests` (2–20 objects) | Each object has `key`, `summary`, `work_type`, `workflow_mode`, optional `depends_on=[]` referencing earlier keys. For explicitly separate RUN lifecycles before planning. |
| `tapl_apply_plan` | None in schema | `plan_id="PLAN-001"`, `title`, `summary`, `objective`, `requirements_trace`, `selected_approach`, `affected_files`, `execution_order`, `risks`, `validation`, `approval_needs`, `notes`, `custom_fields`, `status`. Workflow validation still requires an adequate plan. |
| `tapl_add_finding` | `title` | `source=""`, `finding=""`, `impact=""`, `related_ids=""`. Record decision-relevant evidence and source. |
| `tapl_approve_execution` | `prompt` | `source="explicit_user"` or `"request_user_input"`. With the question tool on a managed RUN, pass the captured `approval_scope`. |
| `tapl_reject_execution` | `prompt` | Same `source` values; preserves the explicit rejection. |
| `tapl_finish_run` | `result` | `expected_run_id`, `memory_candidates`, `memory_uses`, `memory_review`; see completion below. |
| `tapl_finish_archive` | `slug` (1–120 characters) | `summary=""` (at most 2000 characters). After task/batch settlement and completion review. |
| `tapl_discard_run` | `run_id`, `confirmed`, `confirmation_run_id`, `session_id` | Optional `source_db` (exact source filename; omission selects local). All required; see confirmed discard below. |

`work_type`: `answer`, `investigation`, `analysis`, `planning`, `implementation`, `mixed`. `workflow_mode`: `fast`, `standard`, `strict`. TAPL derives `record_mode`; only Fast non-durable answer/investigation/analysis/planning can be lightweight. Durable or Standard/Strict work uses plans/tasks. Different topics normally receive distinct PLANs in one RUN, not separate RUNs.

`tapl_split_run` keys are 1–100 characters, start with an alphanumeric character, and then allow letters, digits, `.`, `_`, or `-`. Forward dependencies are not accepted. Keep all requirements for one outcome in the same topic plan.

For an initial direct implementation request, use `source="explicit_user"` and the exact current user request as `prompt`. For an existing analysis or planning RUN, follow `state_summary.execution_confirmation` in `tapl_get_next` and write receipts. In `finalize_plan`, finalize the intended plans. In `awaiting_user`, capture `scope` before asking with Codex `request_user_input` or Claude Code `AskUserQuestion`. After an explicit affirmative answer, record a summary as `prompt`, use `source="request_user_input"`, and pass the captured value as `approval_scope`. TAPL trusts the agent to record the actual answer and verifies the scope against the current session, RUN, and finalized plans. A stale scope requires a new question. Cancellation, timeout, and missing answers leave execution on hold.

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

Parallel tasks require `execution_mode="parallel"`, `executor_kind="subagent"`, the same plan and nonempty `parallel_group`, completed dependencies, exclusive non-overlapping `owned_paths`, and execution approval. Root dispatches atomically, checks each stored `SubAgent Model`, then spawns actual agents. `execution_metadata` maps task IDs to runtime selection objects, including a complete `model`/`reasoning_effort` pair and rationale when selected. For Claude Code, record `reasoning_effort=""` when unspecified and `model="inherit"` for confirmed host-controlled selection; omit the corresponding native Agent parameters. Root alone writes TAPL state and settles each task with its exact manifest **`execution_id`**. On interruption/spawn failure, recover or cancel the batch before retrying. A stable `batch_id` supports idempotent retry for the same RUN/task set; it is not a way to reuse a different batch.

After a successful start or dispatch, the agent emits one localized TASK notice when execution begins and another when verification begins. A retry of the same start or dispatch does not repeat the notice.

## Sequential lifecycle example

The following is an ordered MCP call outline with `precise` explicitly selected using `taplctl config set workflow.authoring_detail precise`, not a shell command or a script to run blindly. `call(name, arguments)` means your host's MCP invocation. Replace `sid` with the actual hook identity. Load policy, inspect relevant history, and confirm material design choices before finalizing the plan. Record approval only if execution was actually authorized. Use concrete evidence for completion fields.

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
- `memory_uses`: at most 50 objects with `memory_id`, optional `source_db`, positive `revision`, Boolean `source_checked`, and `usage` (1–500 characters). Include only actual use after original-source verification.
- `memory_review`: `{ "decision": "capture" | "skip", "reason": "..." }`; skip requires a reason of 1–240 characters. Omitting both candidates and review leaves `review_required` when review applies.

Capture failures preserve the work result. Inspect the receipt, retry failed slots once with corrected input, then explicitly skip unresolved failures with a reason before archiving. See [Associative memory](../guides/memory.md).

<a id="confirmed-discard"></a>

## Confirmed discard

`tapl_discard_run` requires literal `confirmed=true` and `confirmation_run_id` exactly matching the full selected `run_id`, including case and whitespace. The owner session is mandatory. It processes the selected RUN and all queued RUNs with the same owner and split group, regardless of dependency links. Each RUN is deleted if truly empty or force-archived if it has retained work. Active database executions and batches are cancelled, and no other RUN starts. External agent processes continue running. See [Discard a RUN](../guides/viewer.md#discard-a-run) for the Viewer operation.

## Viewer stdio

The VS Code extension starts a separate local `tapl-mcp` process with `TAPL_MCP_MODE=viewer` and checks `tools/list` for support. The Viewer profile exposes history and memory reads, workspace settings, and these Viewer-specific tools. Its reads do not require a hook session ID. Agent calls use the [common contract](#common-contract).

| Tool | Required arguments | Options and behavior |
| --- | --- | --- |
| `tapl_viewer_get_status` | None | Optional `run_id` and `source_db`. Omit `run_id` for the workspace overview. The Viewer passes the exact RUN ID and source filename when selecting a RUN. Set `full=true` to include record bodies (default `false`). Recent-event options are `include_events` (default `false`) and `events_limit` (default 12, range 0–100). |
| `tapl_viewer_discard_run` | `source_db`, `run_id`, `target_session_id`, `confirmed`, `confirmation_run_id` | Requires the exact local source filename, active RUN ID and stored owner. A legacy owner can be `""`. Pass literal `confirmed=true` and the exact full RUN ID in `confirmation_run_id`. |

## Availability and verification

Tool availability follows the connection profile. Optional semantic dependencies affect search execution, not tool registration. `searchd` is Unix-only. Disabled automatic recall does not remove manual memory inspection. Memory mutation still requires an explicit user request and current revision. See [VS Code capabilities](../guides/vscode.md#shared-viewer-and-capabilities) for older server compatibility.

Schema/session/lifecycle behavior is covered by `test_mcp_native.py`, `test_session_mcp.py`, `test_application.py`, `test_context_optimization.py`, and the memory/discard suites in `tapl/tests`. See [Architecture](../development/architecture.md), [Contributing](../development/contributing.md), and [Workflow](../concepts/workflow.md).
