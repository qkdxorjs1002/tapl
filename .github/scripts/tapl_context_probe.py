"""Measure the public MCP contract and prompt cost in an isolated temporary workspace.

Run with the checkout's Python environment. Output contains synthetic data only.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path

from mcp import Client
from taplctl import config, db, mcp_server, prompt


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def without_descriptions(value):
    if isinstance(value, dict):
        return {key: without_descriptions(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [without_descriptions(item) for item in value]
    return value


def measure(function, count=300):
    samples = []
    for _ in range(count):
        started = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - started) / 1000)
    return {"median_us": statistics.median(samples), "iterations": count}


async def main():
    with tempfile.TemporaryDirectory(prefix="tapl-probe-") as directory:
        root = Path(directory)
        (root / ".git").mkdir()
        db.initialize_workspace(root)
        (root / ".tapl/config.toml").write_text(
            '[search]\nmode="bm25"\n[subagents]\nenabled=true\nsetup_complete=true\n'
            'strategy="balanced"\n[subagents.models]\n"gpt-6-astra"=["high"]\n'
        )
        server = mcp_server.create_server(workspace_root=root)
        native_tools = await server.list_tools()
        tools = [tool.model_dump(mode="json") for tool in native_tools]
        templates = {key: value for key, value in vars(prompt).items()
                     if key.endswith("_TEMPLATE") and isinstance(value, str)}
        renders = {key: prompt.render(value) for key, value in templates.items()}
        selected = config.load(start=root).subagents
        option_renders = []
        for setup, enabled in ((False, True), (True, False), (True, True)):
            for strategy in ("conservative", "balanced", "aggressive"):
                for profiles in (selected.profiles, (), (replace(selected.profiles[0], description="Long custom profile " * 20),)):
                    choice = replace(selected, setup_complete=setup, enabled=enabled,
                                     strategy=strategy, profiles=profiles, preference="품질 우선 " * 10)
                    option_renders.append([
                        prompt.mcp_server_instructions(subagents=choice),
                        prompt.subagent_current_guidance(choice),
                        prompt.user_prompt_submit_guidance(subagents=choice),
                    ])
        async with Client(server) as client:
            entry = (await client.call_tool("tapl_get_next", {})).structured_content
            cached = (await client.call_tool("tapl_get_next", {
                "known_policy_revision": entry["policy_revision"]
            })).structured_content
        bootstrap = getattr(prompt, "mcp_entry_instructions", prompt.mcp_bootstrap_instructions)()
        result = {
            "tool_count": len(tools), "tool_contract_sha256": digest(tools),
            "tool_schema_sha256": digest(without_descriptions(tools)),
            "standalone_renders_sha256": digest(renders),
            "option_renders_sha256": digest(option_renders), "option_render_cases": len(option_renders),
            "bootstrap_chars": len(bootstrap),
            "native_tool_json_chars": len(json.dumps(tools)),
            "per_tool_instructions_projection_chars": len(json.dumps(tools)) + len(tools) * len(bootstrap),
            "full_entry_chars": len(json.dumps(entry)), "retained_entry_chars": len(json.dumps(cached)),
            "prompt_surface_chars": {name: len(function()) for name, function in {
                "entry": prompt.entry_guidance,
                "display": prompt.mcp_tool_result_display_guidance,
                "mode": prompt.workflow_mode_guidance,
                "metadata": prompt.custom_fields_guidance,
                "memory": prompt.memory_guidance,
                "helpers": prompt.subagent_exploration_guidance,
                "policy": lambda: prompt.mcp_server_instructions(subagents=selected),
                "guidance": lambda: prompt.subagent_current_guidance(selected),
                "hook": lambda: prompt.user_prompt_submit_guidance(subagents=selected),
            }.items()},
            "timings": {name: measure(function) for name, function in {
                "session_start": prompt.session_start_guidance,
                "user_prompt": prompt.user_prompt_submit_guidance,
                "stop": prompt.stop_guidance,
                "full_policy": lambda: prompt.mcp_server_instructions(subagents=config.load(start=root).subagents),
            }.items()},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
