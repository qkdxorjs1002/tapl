# Reference benchmark

[Documentation](../README.md) · [한국어](benchmarks.ko.md)

Use these published measurements to assess authoring-detail tradeoffs. The conditions, aggregate results and limitations below describe a reference workload, rather than a performance target.

<a id="authoring-detail-benchmark"></a>

## Measurement conditions

The same SQLite rollback bug fix was measured on 2026-10-29–30 in five independent Morae VMs per condition
(20 runs), using TAPL `2.14.0-beta3` (`2.14.0b3`), Codex CLI `0.159.0`, and `gpt-6.1-sol` with `high` reasoning.
All conditions shared the work request and initial code. TAPL conditions used Strict mode and enforcing hooks,
with recall and subagents disabled. `agents-history` used an AGENTS.md policy for file-based RUN/PLAN/TASK,
optional FINDING and transition history, without TAPL MCP or hooks.
`agents-history` is a comparison condition, not a configuration value. All 20 runs passed functional checks;
the 15 TAPL runs passed core workflow checks, and the five file-history runs passed structural record checks.
The [policy and audit excerpt](#authoring-detail-file-history) below describes the file-history requirements and procedural exceptions.

`precise` was the default in the measured beta3 release. The current `auto` default has not been measured in this comparison, including its mode-based selection; these results do not establish its performance.

Values below are **medians of five samples per condition**; percentages compare with **`tapl + precise` (beta3 baseline)**.
PLAN/TASK counts are observed counts, not limits. Percentage changes are not shown for N/A measurements.

| Condition | Observed PLAN / TASK | Body characters | Authoring argument bytes | Total input tokens¹ | Output tokens | Elapsed time² |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `tapl + precise` (beta3 baseline) | 1 / 3 | 2,227 | 5,257 | 348,705 | 5,607 | 167.7 s |
| `tapl + normal` | 1 / 2 | 1,646 (−26.1%) | 2,758 (−47.5%) | 347,300 (−0.4%) | 4,638 (−17.3%) | 129.9 s (−22.6%) |
| `tapl + minimal` | 1 / 1–2 | 1,290 (−42.1%) | 2,168 (−58.8%) | 364,056 (+4.4%) | 4,031 (−28.1%) | 125.0 s (−25.5%) |
| Without TAPL + AGENTS history (`agents-history`) | 1 / 3–4 | 6,323 (+183.9%) | N/A | 210,919 (−39.5%) | 9,077 (+61.9%) | 184.9 s (+10.3%) |

¹ Input includes cached input. Median uncached input, calculated per sample as `input_tokens - cached_input_tokens`,
was **30,881 / 44,706 / 39,160 / 16,780** for precise / normal / minimal / agents-history. These are separate medians; subtracting column
medians can give a different result. No prices or billing amounts were calculated.

² Time covers the Codex session from launch to exit, including model responses, tool calls and in-session verification.
VM setup and post-session auditing are excluded. Sample time ranges overlap across conditions;
server load and cache effects were not controlled, so these medians do not establish a general speed advantage.

Body characters count the final stored PLAN/TASK Markdown, including task completion and verification results.
Authoring argument bytes sum the arguments of completed `tapl_apply_plan` and `tapl_create_task` calls using the same
UTF-8 JSON serialization, including empty `{}` values; they exclude other tools. These measurements are not token counts.
Input and output tokens cover the **whole conversation**, including code changes, reasoning, tool discovery and verification.
N/A does not mean a measured zero. File-history body counts exclude the first ID/title heading;
RUN/FINDING/HISTORY sizes are preserved separately. MCP argument and typed/custom JSON measurements are N/A.

The file-history samples produced more PLAN/TASK text than precise (6,323 vs 2,227 characters).
Policy wording, formatting, decomposition and actual recorded content differ, so token differences cannot
be attributed solely to MCP versus file writing. This policy does not replicate TAPL's enforcement or all product features.

Normal and minimal reduced record size and output-token medians in this workload; clear overall input savings were not observed.
Provider-side caching, tool discovery and additional regression tests varied between samples. One synthetic task with five
repeats per option does not establish a general quality, speed or cost guarantee.
The agents-history samples were collected later, rather than randomized together with the original 15 TAPL runs;
time and cache effects cannot be separated from condition effects. These measurements do not establish
the value of TAPL's workflow records.

<a id="authoring-detail-file-history"></a>

## File-history policy and audit excerpt

The AGENTS.md policy required the following, without fixed count or length limits:

- Before implementation, write a RUN with request, mode and approval; a finalized PLAN with requirements,
  approach, scope, execution order, risks, rollback and validation; and Pending TASKs with actions and verification.
- Start each TASK immediately before its action and settle it only after verification. Keep a timestamped
  transition history, preserving earlier entries, and record findings with their source and impact when relevant.
- Settle all tasks and record the verified result before archiving the RUN, preserving all record files and references.

Review of the final Markdown and chronological tool traces produced these observations:

| Check | Samples meeting the requirement |
| --- | ---: |
| Structural record checks | 5 / 5 |
| PLAN and TASKs written before implementation | 5 / 5 |
| All TASKs settled before archive | 1 / 5 |
| Earlier HISTORY entries preserved | 4 / 5 |
| No observed procedural exception | 1 / 5 |

Four runs archived before completing the final TASK; one of those also replaced earlier HISTORY lines
while correcting timestamps. Structural success does not establish full procedural compliance.
These are observations, not enforcement guarantees. Only aggregate results and this excerpt are published;
raw conversations, individual records and experiment artifacts are private.

## Apply a measured authoring level

```sh
taplctl config get workflow.authoring_detail
taplctl config set workflow.authoring_detail normal
```

These commands select the writing policy for later work. They do not rerun the benchmark or reproduce its results. See [Authoring detail](../guides/authoring-detail.md) for configuration selection, verification and restoring the default.

## Related pages

[Authoring detail](../guides/authoring-detail.md) · [Workflow](../concepts/workflow.md) · [Contributing and verification](../development/contributing.md)
