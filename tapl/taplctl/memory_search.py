"""Bounded Korean spacing aliases for the derived associative-memory index."""
from __future__ import annotations

import re
import unicodedata


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
