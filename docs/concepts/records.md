# Records and metadata

[Documentation](../README.md) · [한국어](records.ko.md)

TAPL records are structured data in `.tapl/tapl.db`, with readable Markdown bodies rendered from typed fields. Agents create and update them through MCP; the CLI manages the installation. Use this page to understand what belongs in each record and what belongs in `custom_fields`.

## Standard fields carry the work

| Record | Main fields and purpose |
| --- | --- |
| RUN | Request `summary`, `work_type`, `workflow_mode`, derived `record_mode`, session owner, final `result` |
| PLAN | `plan_id`, `title`, `summary`, `objective`, `requirements_trace`, `selected_approach`, `affected_files`, `execution_order`, `risks`, `validation`, `approval_needs`, `notes`, `status` |
| TASK | `task_id`, `title`, `spec_id`, `goal`, `action`, `verification`; `result` on completion; `blocker` and `next_action` when blocked |
| TASK execution | `execution_mode`, `executor_kind`, `parallel_group`, `owned_paths`, `depends_on` |
| FINDING | `title`, `source`, `finding`, `impact`, `related_ids` |
| APPROVAL | Execution decision, authorized scope, and source (`explicit_user` or `request_user_input` for explicit approval) |
| ARCHIVE | Stable slug, summary, and preserved run records for later inspection |

Use stable numeric plan IDs such as `PLAN-001` (`SPEC-001` is also accepted) and task IDs such as `TASK-001`. IDs are unique within a run. A task's `spec_id` references the plan for its topic; it is not a free-form document path.

Executable tasks need actionable goal, action, and verification. Completed tasks need a result and verification evidence; blocked tasks need a blocker and a concrete next action. Parallel tasks also need the execution/ownership fields required by their batch. See [workflow](workflow.md) and [SubAgents](../guides/subagents.md).

## Write through typed fields

Pass plan/task content through the tool's named arguments. TAPL renders the stored Markdown body from its templates when merging a record. Do not replace structured fields with a manually formatted policy dump or invent CLI workflow commands.

For example, these are illustrative `tapl_create_task` arguments after `PLAN-001` exists; replace the session placeholder with the current Codex hook's identity:

```json
{
  "task_id": "TASK-001",
  "title": "Fix configuration path handling",
  "spec_id": "PLAN-001",
  "goal": "Resolve the selected configuration file consistently.",
  "action": "Update the parser to preserve an explicit configuration path.",
  "verification": "Run the parser checks for relative and absolute paths.",
  "session_id": "CURRENT_CODEX_SESSION_ID"
}
```

This illustrates standard fields; execution selection metadata depends on authoring detail, described below. Creation produces a Pending task. Starting and settling it use separate lifecycle tools and require approval where applicable. Exact fields are in the [MCP reference](../reference/mcp.md).

Write multi-line values as Markdown with headings, bullets, or concise labels where useful. Keep natural grammar and spacing in the user's language, including Korean word spacing. Preserve identifiers, paths, commands, and quotations verbatim. For example:

```text
objective: 개발 앱 설정을 준비한 뒤 Task 1개를 실행하고 결과를 확인한다.
action: APP_CONFIG_YML 경로를 확인하고 검증 결과를 기록한다.
```

These are writing examples, not new requirements. TAPL does not reject or automatically rewrite prose based on spacing, and does not restyle historical records.

## Custom fields preserve additional facts

Use `custom_fields` for durable, searchable metadata absent from standard fields: a lasting user constraint, an execution-selection reason, or a domain-specific fact needed to interpret later work. Do not duplicate `goal`, `verification`, or the whole plan in metadata. Put shared facts on the plan and task-specific facts on the task.

For a lasting user preference not already captured by standard fields:

```json
{
  "custom_fields": {
    "User Notes": {
      "category": "Compatibility",
      "content": "The command must remain usable from PowerShell 5.1.",
      "impact": "Check syntax and examples against the supported shell."
    }
  }
}
```

`사용자 참고사항` with `종류`, `내용`, `영향` is the Korean equivalent. Use it only for actual durable user facts, not inferred requirements or transient progress. These names are guidance conventions; arbitrary domain-specific keys are also possible.

Values may use any JSON type. Updates merge top-level keys: omitted keys are preserved, supplied keys replace their values, and a top-level `null` deletes that key. Nested objects are replaced as values, not recursively patched; preserve their required keys/types when updating.

```json
{
  "custom_fields": {
    "Obsolete duplicate": null
  }
}
```

Metadata is included in history search text. Preserve readable descriptions and use the original record as evidence before relying on a search hit. See [search](../guides/search.md).

## Selection metadata depends on authoring detail

At effective `precise` detail (explicitly selected or resolved by `auto` in Strict mode), executable tasks maintain these canonical JSON objects at design and before dispatch, updating them if settlement changes the decision:

| Key | Contents |
| --- | --- |
| `Task Profile` | `name` (selected profile or `none`) and `match_reason` |
| `Task Characteristics` | `independence`, `context`, `risk`, `coordination_cost`, `parallel_value` |
| `Execution Decision` | `executor`, `delegation_reason`, `override`; add `model`, `reasoning_effort`, `model_reason` when selecting a model |

At `normal` or `minimal`, routine root work needs no advisory filler. Model selection and profile overrides still retain concise canonical `Task Profile`, relevant `Task Characteristics`, and `Execution Decision` metadata, including reasons and the selected model/effort when applicable. Durable facts absent from standard fields still belong in `custom_fields` at any detail level. Less prose does not remove approval, dependency, ownership, or verification requirements.

Dispatch writes the legacy `SubAgent Model` field from the manifest, such as `<model-id> (<effort>)`. The root checks it before spawning and preserves it on later updates. Omit it when no SubAgent runs. Existing rationale aliases remain accepted, but new selection metadata should use the canonical objects. See [authoring detail](../guides/authoring-detail.md) and [SubAgents](../guides/subagents.md).

## Findings, current state, and inspection

Store findings that affect requirements, a plan, tasks, or verification, with a source and impact. Prefer a concise conclusion such as “the hook uses the event's exact working folder” and why it changes the approach. Raw search dumps, long candidate lists, and stale facts make future retrieval less useful.

Keep records as current-state snapshots. Update changed facts and preserve omitted fields rather than appending a running transcript. Use task result/blocker fields for execution state and the archive for the final preserved outcome. Associative memory is a separate short lesson linked to a verified original; see [memory](../guides/memory.md).

Inspect plans, tasks, findings, and archives in the [Viewer](../guides/viewer.md), or ask the agent for structured details with `tapl_get_item` (`compact=true` for structured fields) and `tapl_get_archive`. Validation checks IDs, required execution state, approval, dependencies, ownership, and relevant content guidance. A valid record still needs real checks to prove the work correct.
