# Authoring detail

[Documentation](../README.md) · [한국어](authoring-detail.ko.md)

`workflow.authoring_detail` selects how much PLAN/TASK explanation to write and how finely to split work. The default is `precise`. It adjusts repetition and unnecessary splitting while preserving required content, execution approval and verification.

## Choose a level

| Value | PLAN/TASK writing behavior |
| --- | --- |
| `precise` (default) | Preserves current detailed writing and task decomposition. |
| `normal` | Groups related edits and records relevant facts concisely. Separates independently risky work and substantive verification when needed. |
| `minimal` | Focuses on objective, action and verification, references shared plan facts, and combines related changes with their verification. |

```sh
taplctl config set workflow.authoring_detail normal
taplctl config set workflow.authoring_detail minimal
taplctl config get workflow.authoring_detail
taplctl config unset workflow.authoring_detail  # restore precise
```

Normal and minimal impose no fixed task count, character count or token budget. Complexity, risk, ownership,
dependencies and verification boundaries determine decomposition; the existing task-count heuristic does not
apply at these levels. These writing instructions reduce duplication and unnecessary splitting to save tokens;
actual savings depend on the task and model. Fast/Standard/Strict mode, approvals, required fields and completion
verification remain unchanged, including Strict risk, interface, rollback and validation boundaries.

The [configuration file selection rules](configuration.md#workspace-and-file-selection) apply. Use `--config` to select a specific file.
The next full MCP policy lookup delivers the new detail setting and a changed `policy_revision`.

## Required content and custom fields

Keep requirements trace and actionable validation at every level. Tasks retain `goal`, `action` and `verification`, with `result` on completion or `blocker` and `next_action` when blocked. Update only changed fields and reference shared plan facts. Write natural-language values in the user's language with normal grammar and spacing; preserve identifiers, paths, commands and quotations verbatim.

`precise` preserves the existing rule to split every independent edit, migration and verification step. `normal` groups related edits into coherent tasks and separates substantive verification or independently risky work when ownership, dependencies or review differ. `minimal` combines related actions and their verification into the smallest coherent decomposition, splitting for independent risk, ownership, dependencies or substantive verification boundaries.

With `normal` or `minimal`, routine root work needs no advisory `custom_fields` filler. Add concise durable facts only when absent from standard fields. Model selection or profile overrides still retain:

- `Task Profile`: `name`, `match_reason`.
- Relevant `Task Characteristics`: independence, context, risk, coordination cost and parallel value.
- `Execution Decision`: `executor`, `delegation_reason`, `model`, `reasoning_effort`, `model_reason`. Explain overrides.

Reference shared plan facts and preserve JSON keys and types. Keep dispatch's `SubAgent Model`; root verifies the manifest before spawning. Use top-level `null` only to delete duplicate custom fields. Conditional `User Notes` remain for durable user facts absent from standard fields.

## Selection example and verification

A handler change and its regression verification can share a task at `normal` or `minimal` when their ownership and risk boundaries coincide. Separate migration risk or independent verification responsibility still justifies splitting. This is an example, not a target task count.

After changing the setting, check `taplctl config get workflow.authoring_detail` and the next full `tapl_get_next` response's `config.workflow.authoring_detail`, `workflow_policy` and `policy_revision`. Changing the setting does not rewrite old records. Approval, ownership, dependency and required-field errors remain checked at `normal` and `minimal`; only the `precise` task-count heuristic no longer applies.

Reference measurements reduced record-size and output-token medians, while clear total-input savings were not observed. See [Reference benchmark](../reference/benchmarks.md) for values, methods, cached-input accounting and limitations.

## Related pages

[Configuration](configuration.md) · [Records and metadata](../concepts/records.md) · [SubAgents](subagents.md) · [Workflow](../concepts/workflow.md)
