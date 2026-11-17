"""Bounded Korean spacing aliases for the derived associative-memory index."""
from __future__ import annotations

import re
import unicodedata


# Query-time helpers deliberately leave the persisted cue representation alone.
# A long request is sampled at both ends so the final, concrete task survives a
# boilerplate introduction without scanning an unbounded conversation.
_SUMMARY_CHARS = 16384
_SUMMARY_HEAD = 4096
_LEXICAL = re.compile(r"[\w가-힣]+")
_SUMMARY_TOKEN = re.compile(r"[\w가-힣]+(?:[.-][\w가-힣]+)*")
_PARTICLES = ("으로부터", "으로는", "에서는", "에서도", "에게서", "만으로",
              "에서", "에게", "으로", "처럼", "까지", "부터", "이랑",
              "을", "를", "은", "는", "과", "와", "에")
_BOILERPLATE = {
    "a", "an", "and", "are", "as", "at", "be", "can", "could", "do", "for",
    "from", "help", "i", "in", "is", "it", "me", "my", "of", "on", "please",
    "that", "the", "this", "to", "want", "we", "with", "would", "you",
    "그리고", "관련", "기존", "내용", "다시", "대한", "도움", "부탁드립니다",
    "부탁해", "수", "아래", "앞서", "위한", "이번", "있는", "작업", "저는",
    "좀", "주세요", "진행", "합니다", "해", "해줘", "해주세요", "현재", "확인",
}
_TOPICS = {
    "api", "associative", "code", "codex", "database", "developer", "fts", "id", "index", "memory",
    "mindmap", "performance", "python", "recall", "search", "sqlite", "vs", "vscode",
    "검색", "기억", "마인드맵", "메모리", "색인", "성능", "연상", "연상기억",
    "인덱스", "회상",
}


def _without_particle(word: str) -> str:
    # Whole Hangul tokens only: never stem identifiers, filenames or punctuation.
    if re.fullmatch(r"[가-힣]+", word):
        for suffix in _PARTICLES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                return word[:-len(suffix)]
    return word


def select_query(text: str, *, from_summary: bool = False) -> str:
    """Preserve explicit queries; select at most eight request-summary words.

    The caller owns public input validation and explicit-query truncation. Only
    summary fallback removes request boilerplate and favors identifiers/topics.
    Selected words retain their original order and punctuation boundaries.
    """
    if not from_summary:
        return text
    if len(text) > _SUMMARY_CHARS:
        text = text[:_SUMMARY_HEAD] + " | " + text[-(_SUMMARY_CHARS - _SUMMARY_HEAD):]
    text = unicodedata.normalize("NFKC", text)
    candidates = []
    for position, match in enumerate(_SUMMARY_TOKEN.finditer(text)):
        word = match.group()
        normal = _without_particle(word.casefold())
        if normal in _BOILERPLATE or not 2 <= len(normal) <= 80:
            continue
        cost = len(_LEXICAL.findall(word))
        if cost > 8:
            continue
        identifier = bool(re.search(r"[_\d.-]", word) or re.search(r"[a-z][A-Z]", word))
        score = 2 if identifier else 1 if normal in _TOPICS else 0
        candidates.append((score, position, cost, match))
    chosen = []
    budget = 8
    # Recent content wins ties, allowing the concrete request at the end of a
    # long introduction to displace generic opening context.
    for _, position, cost, match in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True):
        if cost <= budget:
            chosen.append((position, match))
            budget -= cost
    chosen.sort(key=lambda item: item[0])
    result = ""
    previous = None
    for _, match in chosen:
        if previous is not None:
            gap = text[previous.end():match.start()]
            # Removed words and punctuation must not become false Hangul joins.
            result += " " if gap.isspace() else " | "
        result += match.group()
        previous = match
    return result


_ALIAS = re.compile(
    r"(?<![\w./:-])(?:mindmap\s+performance|마인드맵\s+성능|"
    r"vs[ \t]+code|vscode|associative[ \t]+memory|연상[ \t]+기억|연상기억|"
    r"mindmap|마인드맵)(?![\w./:-])", re.IGNORECASE,
)
_ALIAS_PAIRS = {
    "vscode": "VS Code", "vs code": "VSCode",
    "associative memory": "연상 기억", "연상 기억": "associative memory",
    "연상기억": "associative memory", "mindmap": "마인드맵", "마인드맵": "mindmap",
    "mindmap performance": "마인드맵 성능", "마인드맵 성능": "mindmap performance",
}


def _aliases(text: str) -> str:
    return _ALIAS.sub(lambda match: _ALIAS_PAIRS[" ".join(match.group().casefold().split())], text)


def _particles(text: str) -> str:
    return re.sub(r"\S+", lambda match: _without_particle(match.group()), text)


def query_variants(text: str) -> list[str]:
    """Return original-first, independent query branches, never synonym bags.

    Aliases are a small explicit vocabulary, not general translation/stemming.
    Each branch can therefore pass recall's automatic approval gate separately.
    """
    normal = unicodedata.normalize("NFKC", text)
    aliases = _aliases(normal)
    particles = _particles(normal)
    combined = _aliases(particles)
    return list(dict.fromkeys((text, aliases, particles, combined)))[:4]


def _korean_spans(text: str):
    """Join complete Hangul words across whitespace, never punctuation/identifiers.

    Four syllables avoid promoting generic short words to automatic cue matches.
    The eight-word window follows recall's query budget; cues are at most 80 chars.
    Single compound words are included so either spelling can match the other.
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    words = list(re.finditer(r"[\w가-힣]+", text))[:8]
    for start in range(len(words)):
        compact = ""
        span = []
        for end in range(start, len(words)):
            current = words[end]
            if not re.fullmatch(r"[가-힣]+", current.group()):
                break
            if end > start and not text[words[end - 1].end():current.start()].isspace():
                break
            compact += current.group()
            span.append(current.group())
            if len(compact) > 80:
                break
            if len(compact) >= 4:
                yield compact, tuple(span)


def korean_aliases(text: str) -> set[str]:
    return {alias for alias, _ in _korean_spans(text)}


def joined_word_spans(text: str):
    """Original words behind aliases, for the existing two-word approval gate."""
    return ((alias, words) for alias, words in _korean_spans(text) if len(words) > 1)


def spacing_key(text: str) -> str:
    text = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return re.sub(r"(?<!\w)[가-힣]+(?: [가-힣]+)+(?!\w)",
                  lambda match: match.group().replace(" ", ""), text)


def query_phrases(text: str) -> set[str]:
    """Whole query windows retain English, identifier and punctuation boundaries."""
    text = unicodedata.normalize("NFKC", text).casefold()
    words = list(re.finditer(r"[\w가-힣]+", text))[:8]
    return {spacing_key(text[start.start():end.end()])
            for index, start in enumerate(words) for end in words[index:]}


def indexed_cues(cues: list[str]) -> str:
    """Keep original terms and add unique aliases within each individual cue."""
    original = " ".join(cues)
    terms = set(re.findall(r"[\w가-힣]+", original.casefold()))
    aliases = set().union(*(korean_aliases(cue) for cue in cues))
    return " ".join([original, *sorted(aliases - terms)]).strip()
