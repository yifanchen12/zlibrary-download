from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path


_SIZE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|TB)", re.I)
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def parse_size(value: str) -> int:
    match = _SIZE_RE.search(value or "")
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}[unit]
    return int(number * factor)


def human_size(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def safe_filename(value: str, fallback: str = "book") -> str:
    cleaned = _INVALID_FILENAME.sub("_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:160].rstrip(" .") or fallback)


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({index}){suffix}"
        index += 1
    return candidate


def split_keywords(value: str) -> tuple[str, ...]:
    parts = re.split(r"[,，;；\n]+", value or "")
    return tuple(part.strip().casefold() for part in parts if part.strip())


def fuzzy_score(query: str, book: object, extra_keywords: tuple[str, ...] = ()) -> int:
    title = str(getattr(book, "title", ""))
    author = str(getattr(book, "author", ""))
    publisher = str(getattr(book, "publisher", ""))
    haystack = " ".join((title, author, publisher)).casefold()
    needle = (query or "").strip().casefold()
    if not needle:
        return 0

    ratio = SequenceMatcher(None, needle, title.casefold()).ratio()
    query_tokens = [token for token in re.split(r"\s+", needle) if token]
    hits = sum(1 for token in query_tokens if token in haystack)
    token_score = hits / max(1, len(query_tokens))
    containment = 1.0 if needle in haystack else 0.0
    extras = [token for token in extra_keywords if token]
    extra_score = (sum(1 for token in extras if token in haystack) / len(extras)) if extras else 0.0
    score = max(ratio * 0.9, token_score * 0.85, containment)
    if extras:
        score = min(1.0, score * 0.8 + extra_score * 0.2)
    return int(round(score * 100))

