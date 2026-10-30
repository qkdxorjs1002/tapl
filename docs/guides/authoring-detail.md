# Authoring detail

[Documentation](../README.md) · [한국어](authoring-detail.ko.md)

`workflow.authoring_detail` controls PLAN/TASK prose and task grouping. The default is `auto`, which selects detail from the active RUN's Fast/Standard/Strict mode. It applies only when records are required: Fast lightweight work still needs no PLAN/TASK. Classification, approval and completion gates remain unchanged.

## Choose a level

| Value | PLAN/TASK writing behavior |
| --- | --- |
| `auto` (default) | Fast → `minimal`, Standard → `normal`, Strict → `precise`. With no active RUN, falls back to `normal`. |
| `precise` | Fixed detailed writing; split independent edits, migrations and verification steps. |
| `normal` | Fixed concise writing; group related edits and separate substantive verification or independently risky work when needed. |
| `minimal` | Fixed objective/action/verification focus; reference shared plan facts and combine related changes with their verification. |

Explicit `precise`, `normal` and `minimal` stay fixed across RUN mode changes. Installation and updates preserve existing explicit selections. To use automatic selection, set `auto` or remove the key:

```sh
taplctl config set workflow.authoring_detail auto
taplctl config set workflow.authoring_detail precise
taplctl config set workflow.authoring_detail normal
taplctl config set workflow.authoring_detail minimal
taplctl config get workflow.authoring_detail
taplctl config unset workflow.authoring_detail  # restore auto
```

No level sets a target task count, character count or token budget. Complexity, risk, ownership, dependencies and verification boundaries determine decomposition. Normal and minimal avoid duplication and unnecessary splitting; actual token savings depend on the work and model. Required risk, interface, recovery/rollback and verification evidence remains necessary, including in Strict mode. Detail never relaxes execution approval, ownership, dependencies or delegation safeguards.

The [configuration file selection rules](configuration.md#workspace-and-file-selection) apply. Use `--config` to select a specific file.

## Required content and custom fields

Keep requirements trace and actionable validation at every level. Tasks retain `goal`, `action` and `verification`, with `result` on completion or `blocker` and `next_action` when blocked. Update changed fields and reference shared plan facts. Write natural-language values in the user's language with normal grammar and spacing; preserve identifiers, paths, commands and quotations verbatim.

The effective level determines grouping. `precise` separates independent edits, migrations and verification. `normal` groups related edits into coherent tasks, separating work when risk, ownership, dependencies or review differ. `minimal` combines related actions and verification into the smallest coherent decomposition while preserving those boundaries.

At effective `normal` or `minimal`, routine root work needs no advisory `custom_fields` filler. Add concise durable facts only when absent from standard fields. Model selection or profile overrides still retain:

- `Task Profile`: `name`, `match_reason`.
- Relevant `Task Characteristics`: independence, context, risk, coordination cost and parallel value.
- `Execution Decision`: `executor`, `delegation_reason`, `model`, `reasoning_effort`, `model_reason`. Explain overrides.

Reference shared plan facts and preserve JSON keys and types. Keep dispatch's `SubAgent Model`; root verifies the manifest before spawning. Use top-level `null` only to delete duplicate custom fields. Conditional `User Notes` remain for durable user facts absent from standard fields. See [Records](../concepts/records.md) and [SubAgents](subagents.md) for the canonical objects and dispatch requirements.

## Selection example and verification

A handler change and its regression verification can share a task at effective `normal` or `minimal` when their ownership and risk boundaries coincide. Separate migration risk or independent verification responsibility still justifies splitting. This is an example, not a target task count.

`taplctl config get workflow.authoring_detail` and `config.workflow.authoring_detail` return the configured selection, including `auto`. Runtime status, `tapl_get_next`, context, validation and applicable write receipts expose a separate `authoring_policy`:

```json
{
  "configured": "auto",
  "effective": "normal",
  "workflow_mode": "standard"
}
```

With no active RUN, `workflow_mode` is `null` and `auto` resolves to `normal`. Resolution uses the selected session's active RUN; another session's mode does not change it.

A mode change updates `policy_revision` because the effective policy is part of the revision. When summarizing, splitting, or archiving a RUN (including automatic Stop archiving) changes mode or effective detail, the receipt sets `policy_refresh_required=true` and prioritizes `tapl_get_next`. Follow that recommendation before continuing; reassess the current PLAN and unfinished TASK evidence, supplementing risks, interfaces, recovery and validation for the new rigor. Policy and validation are reevaluated without automatically rewriting completed or archived records or repartitioning settled tasks.

Retain `known_policy_revision` only while its complete policy, SubAgent guidance and config remain in context. Receiving a new revision in a receipt does not mean the corresponding full policy has been loaded. Omit the revision if that bundle is missing or uncertain; see [MCP entry](../reference/mcp.md#entry-inspection-and-setup).

Validation still checks required fields, approval, ownership and dependencies. For a current finalized Strict plan with unfinished work or no tasks, empty typed `risks`, `affected_files` or `validation` produce non-blocking warnings to supplement actual risk/interface/rollback/verification evidence. Plans with all tasks settled are excluded from these warnings. These structural checks do not assess meaning through NLP, keywords or word counts, and do not prove the evidence is sufficient.

The published beta3 benchmark compared explicit levels, with `precise` as its historical baseline. The current `auto` default has not been measured in that comparison. See [Reference benchmark](../reference/benchmarks.md) for values, methods, cached-input accounting and limitations.

## Related pages

[Configuration](configuration.md) · [Records and metadata](../concepts/records.md) · [SubAgents](subagents.md) · [Workflow](../concepts/workflow.md)
