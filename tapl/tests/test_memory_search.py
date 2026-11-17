"""Existing index spacing boundaries remain stable."""
from taplctl import memory_search


def test_persisted_cues_and_spacing_helpers_keep_existing_boundaries():
    assert memory_search.indexed_cues(["연상 기억", "finish_run", "Developer ID"]) == (
        "연상 기억 finish_run Developer ID 연상기억"
    )
    assert memory_search.indexed_cues(["연상", "기억", "finish_run"]) == "연상 기억 finish_run"
    assert memory_search.indexed_cues(["VSCode", "mindmap performance"]) == "VSCode mindmap performance"
    for cue in ("연상/기억", "연상_기억", "연상 v2 기억"):
        assert "연상기억" not in memory_search.korean_aliases(cue)
        assert "연상기억" not in memory_search.query_phrases(cue)
    assert memory_search.korean_aliases("one two three four five six seven eight 연상기억") == set()
    assert memory_search.query_phrases("Developer ID") == {"developer", "id", "developer id"}
