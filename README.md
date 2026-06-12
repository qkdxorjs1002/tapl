# AGENTS.md

[한국어](README.ko.md)

This repository contains a compact operating workflow for coding agents. The source of truth is `AGENTS.md`: it defines how an agent should inspect context, record requirements, plan work, request execution approval, make changes, verify results, and archive workflow state.

## What This Is

`AGENTS.md` is designed for projects where agent work should stay controlled and traceable. It favors a short approval-based workflow over immediate edits to project files.

The workflow is built around these rules:

- Inspect the active workflow and worktree before starting non-trivial work.
- Record confirmed requirements before planning complex or approval-gated changes.
- Plan before implementation, and connect each plan item back to a requirement.
- Ask for execution approval before modifying durable project files.
- Keep task state current while work is being executed.
- Verify the result before marking work complete.
- Archive workflow files when there is no remaining actionable work.
- Never overwrite, discard, commit, push, rebase, or reset user changes unless explicitly asked.

## Workflow Files

Active workflow files live under `.agent-workflow/`. They are working state, not project deliverables, and should stay short, practical, and current.

- `.agent-workflow/request.md`: confirmed requirements, assumptions, open questions, exclusions, and references.
- `.agent-workflow/plan.md`: objective, constraints, selected approach, affected files, execution order, risks, validation, and approval items.
- `.agent-workflow/task.md`: current executable tasks with `TASK-*` IDs and explicit states.
- `.agent-workflow/speedwagon.md`: decision-relevant external findings.
- `.agent-workflow/archive/<timestamp>-<task-slug>/`: archived workflow history with a concise summary.

Use only the files needed for the current task. When active workflow files are stale or complete, archive them instead of letting them become logs.

## ID Conventions

The workflow uses stable IDs to keep decisions traceable:

- `REQ-*` for confirmed requirements.
- `SPEC-*` for plan items that trace back to requirements.
- `TASK-*` for executable work that traces back to plan items.

These IDs are not ceremony. They make it clear what was requested, what approach was approved, and what was actually executed.

## Repository Layout

- `AGENTS.md`: the workflow and operating rules.
- `.codex/config.toml`: Codex defaults for this setup, including model, reasoning effort, personality, and enabled features.
- `.codex/agents/`: subagent definitions for `junior-worker`, `senior-worker`, and `specialist-worker`.
- `README.md`: English overview.
- `README.ko.md`: Korean overview.

## Applying The Workflow

For a project, place `AGENTS.md` at the project root so agents can read it before working. `AGENTS.md` defines the project workflow rules: inspect state, record requirements when needed, plan, ask before durable edits, execute, verify, and archive.

The `.codex` files customize Codex behavior around those rules. The current setup includes `multi_agent = true`, `default_mode_request_user_input = true`, and worker agents for junior, senior, and specialist task routing.

To apply the `.codex` setup globally, merge this repo's `.codex/config.toml` into your global Codex config file, usually `~/.codex/config.toml`, and copy the agent TOML files from `.codex/agents/` into the global agent directory, usually `~/.codex/agents/`. Merge carefully instead of blindly overwriting existing settings, especially if you already have model, approval, feature, or agent configuration.

To apply it to one project, place `<project>/.codex/config.toml` and `<project>/.codex/agents/` in that project's root alongside `AGENTS.md`. This keeps project-specific behavior versioned with the project.

Use global configuration for personal defaults you want across repositories. Use project-level configuration for team rules, repo-specific workflow behavior, or agents that should travel with the project.

The workflow does not require every file for every request. Small questions may need no workflow files. Non-trivial or approval-gated work should use the minimum set needed to keep requirements, planning, tasks, and verification clear.

## Operating View

This repository treats an agent as a careful collaborator, not an autonomous executor. The expected pattern is: read the current state, clarify scope, plan the change, ask before editing durable files, verify the result, and report what changed.
