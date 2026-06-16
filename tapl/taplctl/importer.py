"""Markdown importer for legacy .agent-workflow content."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

from . import db


@dataclass(frozen=True)
class MarkdownSource:
    source: str
    text: str
    created_at: str | None = None


@dataclass(frozen=True)
class MarkdownGroup:
    key: str
    files: dict[str, MarkdownSource]


@dataclass(frozen=True)
class GroupMetadata:
    slug: str
    archive_id: str
    created_at: str
    is_archive: bool


@dataclass(frozen=True)
class ParsedTask:
    task_id: str
    title: str
    status: str
    spec_id: str
    goal: str
    action: str
    required_subagent: str
    verification: str
    result: str
    blocker: str
    next_action: str
    raw_text: str


@dataclass(frozen=True)
class ParsedFinding:
    finding_id: str
    title: str
    source: str
    finding: str
    impact: str
    related_ids: str
    raw_text: str


@dataclass(frozen=True)
class ParsedPlan:
    plan_id: str
    title: str
    body: str
    raw_text: str


def import_markdown(
    conn: sqlite3.Connection,
    *,
    path: Path,
    dry_run: bool = False,
    migrate_existing: bool = False,
) -> dict[str, Any]:
    root = path.resolve()
    files = sorted(file for file in root.rglob("*.md") if file.is_file()) if root.exists() else []
    archive_files = [file for file in files if "archive" in file.relative_to(root).parts]
    sources = [
        MarkdownSource(
            source=file.relative_to(root).as_posix(),
            text=file.read_text(encoding="utf-8", errors="replace"),
        )
        for file in files
    ]

    payload: dict[str, Any] = {
        "path": str(root),
        "exists": root.exists(),
        "dry_run": dry_run,
        "migrate_existing": migrate_existing,
        "markdown_files": len(files),
        "archive_markdown_files": len(archive_files),
        "active_markdown_files": len(files) - len(archive_files),
    }

    import_result = migrate_sources(conn, sources=sources, dry_run=dry_run) if sources else empty_migration_result()
    payload.update({f"filesystem_{key}": value for key, value in import_result.items()})

    if migrate_existing:
        existing_result = migrate_existing_legacy_imports(conn, dry_run=dry_run)
        payload.update({f"existing_{key}": value for key, value in existing_result.items()})

    payload["ok"] = True
    return payload


def migrate_existing_legacy_imports(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict[str, Any]:
    runs = conn.execute(
        """
        SELECT DISTINCT r.*
        FROM workflow_runs r
        JOIN items i ON i.run_id = r.id
        WHERE r.slug = 'legacy-markdown-import'
          AND i.stable_id LIKE 'MD-%'
          AND i.source IS NOT NULL
        ORDER BY r.created_at
        """
    ).fetchall()
    sources: list[MarkdownSource] = []
    legacy_run_ids: list[str] = []

    for run in runs:
        legacy_run_ids.append(run["id"])
        for item in conn.execute(
            """
            SELECT source, raw_text, body, created_at
            FROM items
            WHERE run_id = ?
              AND stable_id LIKE 'MD-%'
              AND source IS NOT NULL
            ORDER BY source
            """,
            (run["id"],),
        ):
            sources.append(
                MarkdownSource(
                    source=item["source"],
                    text=item["raw_text"] or item["body"],
                    created_at=item["created_at"],
                )
            )

    result = migrate_sources(conn, sources=sources, dry_run=dry_run)
    result["legacy_runs"] = len(legacy_run_ids)
    result["legacy_run_ids"] = legacy_run_ids
    result["removed_legacy_runs"] = 0
    if not dry_run and sources:
        for run_id in legacy_run_ids:
            delete_run(conn, run_id)
        conn.commit()
        result["removed_legacy_runs"] = len(legacy_run_ids)
    return result


def migrate_sources(
    conn: sqlite3.Connection,
    *,
    sources: list[MarkdownSource],
    dry_run: bool,
) -> dict[str, Any]:
    groups = group_sources(sources)
    group_payloads = [describe_group(group) for group in groups]
    result: dict[str, Any] = {
        "groups": len(groups),
        "archive_groups": sum(1 for group in groups if group.key.startswith("archive/")),
        "active_groups": sum(1 for group in groups if group.key == "active"),
        "planned": group_payloads,
        "created_runs": 0,
        "created_archives": 0,
        "created_plan_items": 0,
        "created_task_items": 0,
        "created_finding_items": 0,
    }
    if dry_run:
        return result

    for group in groups:
        imported = import_group(conn, group)
        result["created_runs"] += 1
        result["created_archives"] += 1
        result["created_plan_items"] += imported["plan_items"]
        result["created_task_items"] += imported["task_items"]
        result["created_finding_items"] += imported["finding_items"]
    return result


def empty_migration_result() -> dict[str, Any]:
    return {
        "groups": 0,
        "archive_groups": 0,
        "active_groups": 0,
        "planned": [],
        "created_runs": 0,
        "created_archives": 0,
        "created_plan_items": 0,
        "created_task_items": 0,
        "created_finding_items": 0,
    }


def group_sources(sources: list[MarkdownSource]) -> list[MarkdownGroup]:
    grouped: dict[str, dict[str, MarkdownSource]] = {}
    for source in sources:
        path = PurePosixPath(source.source)
        parts = path.parts
        if len(parts) >= 3 and parts[0] == "archive":
            key = f"archive/{parts[1]}"
            name = parts[-1].lower()
        else:
            key = "active"
            name = parts[-1].lower()
        grouped.setdefault(key, {})[name] = source

    def sort_key(group: MarkdownGroup) -> tuple[int, str]:
        return (0 if group.key.startswith("archive/") else 1, group.key)

    return sorted((MarkdownGroup(key, files) for key, files in grouped.items()), key=sort_key)


def describe_group(group: MarkdownGroup) -> dict[str, Any]:
    plans = parse_plans(group.files.get("plan.md"))
    tasks = parse_tasks(group.files.get("task.md"))
    findings = parse_findings(group.files.get("finding.md")) + parse_findings(group.files.get("speedwagon.md"))
    metadata = metadata_for_group(group)
    return {
        "key": group.key,
        "slug": metadata.slug,
        "archive_id": metadata.archive_id,
        "files": sorted(group.files),
        "plan_items": len(plans),
        "task_items": len(tasks),
        "finding_items": len(findings),
    }


def import_group(conn: sqlite3.Connection, group: MarkdownGroup) -> dict[str, int]:
    metadata = metadata_for_group(group)
    summary_sections = sections_for(group.files.get("summary.md"))
    request_sections = sections_for(group.files.get("request.md"))
    plan_sections = sections_for(group.files.get("plan.md"))
    request_summary = compact_text(
        summary_sections.get("Original Request")
        or request_sections.get("Summary")
        or plan_sections.get("Request Summary")
        or ""
    )
    archive_summary = compact_text(
        summary_sections.get("Selected Plan")
        or summary_sections.get("Completed Work")
        or request_summary
        or f"Imported legacy markdown workflow group {group.key}."
    )

    replace_archive(conn, metadata.archive_id)
    run_id = run_id_for(metadata.archive_id)
    conn.execute(
        """
        INSERT INTO workflow_runs(id, slug, status, request_summary, created_at, updated_at, archived_at)
        VALUES(?, ?, 'archived', ?, ?, ?, ?)
        """,
        (run_id, metadata.slug, request_summary, metadata.created_at, metadata.created_at, metadata.created_at),
    )
    conn.execute(
        "INSERT INTO archives(id, run_id, slug, summary, created_at) VALUES(?, ?, ?, ?, ?)",
        (metadata.archive_id, run_id, metadata.slug, archive_summary, metadata.created_at),
    )
    conn.commit()

    counts = {"plan_items": 0, "task_items": 0, "finding_items": 0}
    for plan in parse_plans(group.files.get("plan.md")):
        db.upsert_item(
            conn,
            kind="plan",
            stable_id=plan.plan_id,
            title=plan.title,
            body=plan.body,
            raw_text=plan.raw_text,
            source=group.files["plan.md"].source,
            run_id=run_id,
            archived=True,
            status="Imported",
        )
        counts["plan_items"] += 1

    for task in parse_tasks(group.files.get("task.md")):
        upsert_imported_task(conn, task=task, source=group.files["task.md"].source, run_id=run_id)
        counts["task_items"] += 1

    for finding in parse_findings(group.files.get("finding.md")) + parse_findings(group.files.get("speedwagon.md")):
        source_file = group.files.get("finding.md") or group.files.get("speedwagon.md")
        upsert_imported_finding(conn, finding=finding, source_file=source_file.source if source_file else "", run_id=run_id)
        counts["finding_items"] += 1

    return counts


def parse_plans(source: MarkdownSource | None) -> list[ParsedPlan]:
    if source is None:
        return []

    lines = source.text.splitlines()
    plans: list[ParsedPlan] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\s*-\s+(SPEC-\d+):\s+(.+?)\s*$", line)
        if not match:
            index += 1
            continue

        block = [line]
        index += 1
        while index < len(lines) and not re.match(r"^\s*-\s+SPEC-\d+:", lines[index]):
            if re.match(r"^##\s+", lines[index]):
                break
            block.append(lines[index])
            index += 1

        title, trace = split_title_trace(match.group(2))
        body_parts = []
        if trace:
            body_parts.append(f"Trace: {trace}")
        body_parts.append(clean_block("\n".join(block[1:])))
        body = "\n".join(part for part in body_parts if part).strip()
        plans.append(
            ParsedPlan(
                plan_id=match.group(1),
                title=title,
                body=body,
                raw_text="\n".join(block).strip(),
            )
        )

    if plans:
        return plans

    body = strip_markdown_heading(source.text)
    if not body:
        return []
    return [
        ParsedPlan(
            plan_id="PLAN-001",
            title=first_heading(source.text) or "Plan",
            body=body,
            raw_text=source.text,
        )
    ]


def parse_tasks(source: MarkdownSource | None) -> list[ParsedTask]:
    if source is None:
        return []

    lines = source.text.splitlines()
    tasks: list[ParsedTask] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\s*-\s+(TASK-\d+)\s+\[([^\]]+)\]:\s+(.+?)\s*$", line)
        if not match:
            index += 1
            continue

        block = [line]
        index += 1
        while index < len(lines) and not re.match(r"^\s*-\s+TASK-\d+\s+\[[^\]]+\]:", lines[index]):
            if re.match(r"^##\s+", lines[index]):
                break
            block.append(lines[index])
            index += 1

        title, spec_id = split_title_trace(match.group(3))
        fields = parse_bullet_fields(block[1:])
        status = normalize_task_status(match.group(2))
        tasks.append(
            ParsedTask(
                task_id=match.group(1),
                title=title,
                status=status,
                spec_id=spec_id,
                goal=fields.get("Goal") or title,
                action=fields.get("Action", ""),
                required_subagent=normalize_subagent(fields.get("Required Subagent", "")),
                verification=fields.get("Verification", ""),
                result=fields.get("Result", ""),
                blocker=fields.get("Blocker", ""),
                next_action=fields.get("Next action") or fields.get("Next Action", ""),
                raw_text="\n".join(block).strip(),
            )
        )
    return tasks


def parse_findings(source: MarkdownSource | None) -> list[ParsedFinding]:
    if source is None:
        return []

    lines = source.text.splitlines()
    findings: list[ParsedFinding] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\s*-\s+(FINDING-\d+):\s+(.+?)\s*$", line)
        if not match:
            index += 1
            continue

        block = [line]
        index += 1
        while index < len(lines) and not re.match(r"^\s*-\s+FINDING-\d+:", lines[index]):
            if re.match(r"^##\s+", lines[index]):
                break
            block.append(lines[index])
            index += 1

        title, related_ids = split_title_trace(match.group(2))
        fields = parse_bullet_fields(block[1:])
        findings.append(
            ParsedFinding(
                finding_id=match.group(1),
                title=title,
                source=fields.get("Source", ""),
                finding=fields.get("Finding", clean_block("\n".join(block[1:]))),
                impact=fields.get("Impact", ""),
                related_ids=related_ids,
                raw_text="\n".join(block).strip(),
            )
        )
    return findings


def upsert_imported_task(conn: sqlite3.Connection, *, task: ParsedTask, source: str, run_id: str) -> None:
    body = "\n".join(
        part
        for part in [
            f"Goal: {task.goal}" if task.goal else "",
            f"Action: {task.action}" if task.action else "",
            f"Verification: {task.verification}" if task.verification else "",
            f"Result: {task.result}" if task.result else "",
            f"Blocker: {task.blocker}" if task.blocker else "",
            f"Next action: {task.next_action}" if task.next_action else "",
        ]
        if part
    )
    item = db.upsert_item(
        conn,
        kind="task",
        stable_id=task.task_id,
        title=task.title,
        body=body,
        raw_text=task.raw_text,
        status=task.status,
        source=source,
        run_id=run_id,
        archived=True,
    )
    conn.execute(
        """
        INSERT INTO tasks(item_id, task_id, spec_id, goal, action, required_subagent, verification, result, blocker, next_action)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          spec_id = excluded.spec_id,
          goal = excluded.goal,
          action = excluded.action,
          required_subagent = excluded.required_subagent,
          verification = excluded.verification,
          result = excluded.result,
          blocker = excluded.blocker,
          next_action = excluded.next_action
        """,
        (
            item["id"],
            task.task_id,
            task.spec_id,
            task.goal,
            task.action,
            task.required_subagent,
            task.verification,
            task.result,
            task.blocker,
            task.next_action,
        ),
    )
    conn.commit()


def upsert_imported_finding(
    conn: sqlite3.Connection,
    *,
    finding: ParsedFinding,
    source_file: str,
    run_id: str,
) -> None:
    item = db.upsert_item(
        conn,
        kind="finding",
        stable_id=finding.finding_id,
        title=finding.title,
        body=finding.finding,
        raw_text=finding.raw_text,
        source=finding.source or source_file,
        run_id=run_id,
        archived=True,
    )
    conn.execute(
        """
        INSERT INTO findings(item_id, related_ids, impact)
        VALUES(?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          related_ids = excluded.related_ids,
          impact = excluded.impact
        """,
        (item["id"], finding.related_ids, finding.impact),
    )
    conn.commit()


def metadata_for_group(group: MarkdownGroup) -> GroupMetadata:
    if group.key.startswith("archive/"):
        archive_dir = group.key.split("/", 1)[1]
        match = re.match(r"^(\d{8})-(\d{6})-(.+)$", archive_dir)
        if match:
            date, time, slug = match.groups()
            created_at = (
                f"{date[0:4]}-{date[4:6]}-{date[6:8]}T"
                f"{time[0:2]}:{time[2:4]}:{time[4:6]}+00:00"
            )
            archive_id = (
                f"{date[0:4]}-{date[4:6]}-{date[6:8]}T"
                f"{time[0:2]}{time[2:4]}{time[4:6]}Z-{slug}"
            )
            return GroupMetadata(slug=slug, archive_id=archive_id, created_at=created_at, is_archive=True)
        slug = slugify(archive_dir)
        now = group_created_at(group)
        return GroupMetadata(slug=slug, archive_id=f"{archive_id_time(now)}-{slug}", created_at=now, is_archive=True)

    now = group_created_at(group)
    return GroupMetadata(
        slug="legacy-active-workflow",
        archive_id="legacy-active-workflow",
        created_at=now,
        is_archive=False,
    )


def group_created_at(group: MarkdownGroup) -> str:
    created_values = sorted(source.created_at for source in group.files.values() if source.created_at)
    return created_values[0] if created_values else db.utc_now()


def archive_id_time(created_at: str) -> str:
    return created_at.replace("-", "").replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")


def run_id_for(archive_id: str) -> str:
    return "legacy-md-" + db.content_hash([archive_id])[:32]


def replace_archive(conn: sqlite3.Connection, archive_id: str) -> None:
    row = conn.execute("SELECT run_id FROM archives WHERE id = ?", (archive_id,)).fetchone()
    if row:
        delete_run(conn, row["run_id"])
    run_id = run_id_for(archive_id)
    row = conn.execute("SELECT id FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
    if row:
        delete_run(conn, run_id)
    conn.commit()


def delete_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute("DELETE FROM items_fts WHERE rowid IN (SELECT id FROM items WHERE run_id = ?)", (run_id,))
    conn.execute("DELETE FROM workflow_runs WHERE id = ?", (run_id,))


def sections_for(source: MarkdownSource | None) -> dict[str, str]:
    return markdown_sections(source.text) if source else {}


def markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def parse_bullet_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        match = re.match(r"^\s+-\s+([^:]+):\s*(.*)$", line)
        if match:
            current = match.group(1).strip()
            fields[current] = [match.group(2).strip()]
            continue
        if current and line.strip():
            fields[current].append(line.strip())
    return {key: clean_block("\n".join(value)) for key, value in fields.items()}


def split_title_trace(text: str) -> tuple[str, str]:
    text = text.strip()
    match = re.match(r"^(.*?)\s+\(([^)]*(?:REQ|SPEC|TASK|FINDING)-[^)]*)\)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def normalize_task_status(status: str) -> str:
    normalized = status.strip()
    return normalized if normalized in db.TASK_STATUSES else "Pending"


def normalize_subagent(value: str) -> str:
    match = re.search(r"\[(@[^\]]+)\]", value)
    if match:
        return match.group(1)
    return value.strip()


def clean_block(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def compact_text(text: str, limit: int = 360) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "-", value.strip()).strip("-").lower()
    return slug or "legacy-markdown-import"


def first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return None


def strip_markdown_heading(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).strip()
    return text.strip()
