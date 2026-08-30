from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Book:
    source_id: str
    title: str
    author: str
    publisher: str
    year: str
    language: str
    file_format: str
    size_bytes: int
    detail_url: str
    cover_url: str = ""
    match_score: int = 0


@dataclass(slots=True)
class DownloadResult:
    path: str
    size_bytes: int
    history_id: int
    skipped: bool = False


@dataclass(slots=True)
class BatchOptions:
    query: str
    extra_keywords: tuple[str, ...]
    threshold: int
    target_bytes: int
    max_pages: int
    output_dir: str
    preferred_format: str = "ANY"

