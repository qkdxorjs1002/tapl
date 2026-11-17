"""Query-time expansion must not change persisted cues or approval boundaries."""
import re
import unicodedata

import pytest

from taplctl import memory_search


@pytest.mark.parametrize("query,alias", [
    ("VSCode", "VS Code"), ("VS Code", "VSCode"),
    ("vScOdE", "VS Code"), ("ＶＳＣｏｄｅ", "VS Code"),
    ("associative memory", "연상 기억"), ("연상 기억", "associative memory"),
    ("연상기억", "associative memory"),
    ("mindmap", "마인드맵"), ("마인드맵", "mindmap"),
    ("mindmap performance", "마인드맵 성능"),
    ("마인드맵 성능", "mindmap performance"),
])
def test_explicit_technical_alias_pairs(query, alias):
    variants = memory_search.query_variants(query)
    assert variants[0] == query
    assert alias in variants
    assert query + " " + alias not in variants
    assert len(variants) == len(set(variants)) <= 4


@pytest.mark.parametrize("query", [
    "memory", "performance", "성능", "기억", "연상", "연상기", "상기억",
    "notvscode", "VSCodeX", "vscode_settings", "VSCode.json", "VS-Code",
    "연상/기억", "연상_기억", "연상 a 기억", "비연상기억", "연상기억X",
    "memory recall", "finish_run", "Developer ID", "settings-host.cjs",
    "한국어띄어쓰기를,", "한국어띄어쓰기를.json", "finish_run을", "기억을",
])
def test_generic_partial_code_and_punctuation_are_not_expanded(query):
    assert memory_search.query_variants(query) == [query]


def test_particles_are_conservative_whole_hangul_tokens():
    query = "한국어띄어쓰기를 마인드맵에서 finish_run Developer ID settings-host.cjs"
    variants = memory_search.query_variants(query)
    assert variants == [
        query,
        "한국어띄어쓰기 마인드맵 finish_run Developer ID settings-host.cjs",
        "한국어띄어쓰기 mindmap finish_run Developer ID settings-host.cjs",
    ]


def test_original_order_nfkc_and_combination_are_deterministic():
    query = "  ＶＳＣｏｄｅ\t한국어띄어쓰기를  "
    assert memory_search.query_variants(query) == [
        query, "  VS Code\t한국어띄어쓰기를  ",
        "  VSCode\t한국어띄어쓰기  ", "  VS Code\t한국어띄어쓰기  ",
    ]
    decomposed = unicodedata.normalize("NFD", "한국어띄어쓰기를")
    assert memory_search.query_variants(decomposed) == [
        decomposed, "한국어띄어쓰기를", "한국어띄어쓰기",
    ]


@pytest.mark.parametrize("query", [
    "  finish_run\tDeveloper ID settings-host.cjs!  ",
    "one two three four five six seven eight 연상기억", "", "x" * 2001,
])
def test_explicit_selection_is_exactly_unchanged(query):
    assert memory_search.select_query(query) == query


def test_summary_recovers_late_topic_under_eight_lexical_words():
    summary = "이전 작업 내용을 확인하고 도움을 주세요. " * 1000 + "연상 기억 검색"
    selected = memory_search.select_query(summary, from_summary=True)
    assert "연상 기억 검색" in selected
    assert len(re.findall(r"[\w가-힣]+", selected)) <= 8
    assert selected == memory_search.select_query(summary, from_summary=True)


def test_summary_keeps_identifiers_and_filename_meaningful():
    selected = memory_search.select_query(
        "Please help me with this task: finish_run Developer ID settings-host.cjs", from_summary=True,
    )
    assert "finish_run" in selected
    assert "Developer ID" in selected
    assert "settings-host.cjs" in selected
    assert len(re.findall(r"[\w가-힣]+", selected)) <= 8


def test_summary_never_creates_spacing_joins_across_removed_tokens_or_punctuation():
    for query in ("연상/기억", "연상 please 기억", "연상 finish_run 기억"):
        selected = memory_search.select_query(query, from_summary=True)
        assert "연상기억" not in memory_search.korean_aliases(selected)


def test_summary_scan_is_bounded_at_both_ends():
    head = "VSCode "
    tail = " 연상 기억 검색"
    # The excluded middle must not affect selection or introduce a huge token.
    left = head + "x" * 100000 + tail
    right = head + "x" * 20000 + "middle_secret_token" + "x" * 80000 + tail
    selected = memory_search.select_query(left, from_summary=True)
    assert selected == memory_search.select_query(right, from_summary=True)
    assert "middle_secret_token" not in selected
    assert len(re.findall(r"[\w가-힣]+", selected)) <= 8
    assert len(selected) < 2000


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
