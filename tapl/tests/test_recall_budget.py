"""The final automatic envelope owns one exact UTF-8 budget."""
from copy import deepcopy
import json

import pytest

from taplctl import recall


def size(payload):
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def memory(index=0, *, note="A complete note.", item_id=None):
    source = {"run_id": f"original-{index}", "kind": "run", "archive_id": f"archive-{index}"}
    if item_id is not None:
        source.update(kind="item", item_id=item_id)
    return {"id": f"memory-{index}", "revision": 1, "note": note,
            "source_db": "tapl-peer.db", "source": {**source, "source_db": "tapl-peer.db"},
            "cue": ["manual detail"], "matched_cues": [], "source_record": {"private": "original"}}


def payload(memories, **extra):
    return {"memories": memories, "query": "", "total": len(memories), "limit": 3, "offset": 0,
            "diagnostics": {"stored_count": len(memories), "matched_count": len(memories),
                            "last_capture_error": None}, **extra}


@pytest.mark.parametrize("target", [3599, 3600, 3601])
def test_exact_final_serialized_boundary(target):
    candidate = memory(note="X")
    base = size(recall.finalize_automatic_recall(payload([deepcopy(candidate)])))
    candidate["note"] = "X" * (1 + target - base)
    result = recall.finalize_automatic_recall(payload([candidate]))
    assert size(result) <= recall.AUTOMATIC_RECALL_MAX_BYTES
    if target <= recall.AUTOMATIC_RECALL_MAX_BYTES:
        assert size(result) == target
        assert result["memories"][0]["note"] == candidate["note"]
        assert result["status"] == "recalled"
    else:
        assert result["memories"] == []
        assert result["status"] == "empty"
        assert result["diagnostics"]["budget_dropped"] == 1


def test_oversized_candidate_does_not_displace_three_later_intact_notes():
    notes = ["가" * 239 + suffix for suffix in "나다라"]
    candidates = [memory(note="X" * 4000), *[memory(i + 1, note=note) for i, note in enumerate(notes)]]
    for candidate in candidates:
        candidate["matched_cues"] = ["optional " * 500, "another cue"]
    stats = {}
    result = recall.finalize_automatic_recall(payload(candidates), stats=stats)
    assert [entry["note"] for entry in result["memories"]] == notes
    assert [entry["id"] for entry in result["memories"]] == ["memory-1", "memory-2", "memory-3"]
    assert all("matched_cues" not in entry for entry in result["memories"])
    assert result["diagnostics"]["matched_count"] == 4
    assert result["diagnostics"]["injected_count"] == 3
    assert stats["budget_dropped"] == 1
    assert stats["selected_count"] == 4
    assert stats["selected_count"] == stats["returned_count"] + stats["budget_dropped"]
    assert stats["final_bytes"] == size(result) <= recall.AUTOMATIC_RECALL_MAX_BYTES


def test_metadata_only_envelope_and_errors_always_fit():
    result = recall.finalize_automatic_recall(payload(
        [], query="긴쿼리" * 2000, source_errors=[
            {"source_db": "long-source" * 100, "error": "긴 오류 " * 1000, "code": "history_unavailable"}
            for _ in range(20)], diagnostics={"stored_count": 0, "matched_count": 0,
                                            "last_capture_error": "private " * 2000},
        unexpected_metadata="never copied " * 2000))
    assert size(result) <= recall.AUTOMATIC_RECALL_MAX_BYTES
    assert result["query"] == ""
    assert result["source_errors"] == []
    assert result["source_errors_omitted"] == 20
    assert result["diagnostics"]["injected_count"] == 0
    assert "last_capture_error" not in result["diagnostics"]


@pytest.mark.parametrize("item_id", [None, 0, -1, True, "1"])
def test_invalid_item_pointer_is_never_downgraded_to_run(item_id):
    candidate = memory()
    candidate["source"].update(kind="item", item_id=item_id)
    result = recall.finalize_automatic_recall(payload([candidate]))
    assert result["memories"] == []
    assert result["diagnostics"]["reason"] == "invalid_source"


def test_compact_item_and_run_provenance_and_optional_single_cue():
    candidates = [memory(item_id=7), memory(1)]
    for candidate in candidates:
        candidate["matched_cues"] = ["first cue", "second cue"]
    originals = deepcopy(candidates)
    result = recall.finalize_automatic_recall(payload(candidates))
    item, run = result["memories"]
    assert set(item) == {"id", "revision", "note", "source_db", "source", "matched_cues"}
    assert item["source"] == {"run_id": "original-0", "kind": "item", "item_id": 7}
    assert run["source"] == {"run_id": "original-1", "kind": "run", "archive_id": "archive-1"}
    assert item["matched_cues"] == run["matched_cues"] == ["first cue"]
    assert candidates == originals


def test_entirely_dropped_candidates_and_memory_limit():
    stats = {}
    result = recall.finalize_automatic_recall(payload([memory(i, note="X" * 4000) for i in range(5)]), stats=stats)
    assert result["memories"] == []
    assert result["diagnostics"]["budget_dropped"] == stats["budget_dropped"] == 5
    assert stats["returned_count"] == 0
    result = recall.finalize_automatic_recall(payload([memory(i) for i in range(5)]))
    assert len(result["memories"]) == recall.AUTOMATIC_RECALL_LIMIT
