from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator

from .config import app_data_dir
from .models import Book


class HistoryDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "history.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author TEXT,
                    publisher TEXT,
                    year TEXT,
                    language TEXT,
                    file_format TEXT,
                    expected_bytes INTEGER DEFAULT 0,
                    actual_bytes INTEGER DEFAULT 0,
                    detail_url TEXT,
                    local_path TEXT,
                    query TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_download_source_status ON downloads(source_id, status)"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def begin(self, book: Book, query: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO downloads (
                    source_id, title, author, publisher, year, language,
                    file_format, expected_bytes, detail_url, query, status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'downloading', ?)
                """,
                (
                    book.source_id,
                    book.title,
                    book.author,
                    book.publisher,
                    book.year,
                    book.language,
                    book.file_format,
                    book.size_bytes,
                    book.detail_url,
                    query,
                    self._now(),
                ),
            )
            return int(cursor.lastrowid)

    def complete(self, history_id: int, path: str, size_bytes: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE downloads SET status='completed', local_path=?, actual_bytes=?,
                    completed_at=?, error=NULL WHERE id=?
                """,
                (path, size_bytes, self._now(), history_id),
            )

    def fail(self, history_id: int, error: str, status: str = "failed") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE downloads SET status=?, error=?, completed_at=? WHERE id=?",
                (status, error[:1000], self._now(), history_id),
            )

    def completed(self, source_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT * FROM downloads WHERE source_id=? AND status='completed'
                ORDER BY id DESC LIMIT 1
                """,
                (source_id,),
            ).fetchone()

    def recent(self, limit: int = 1000) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute("SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            )

    def completed_total(self, query: str = "") -> int:
        sql = "SELECT COALESCE(SUM(actual_bytes), 0) FROM downloads WHERE status='completed'"
        params: tuple[object, ...] = ()
        if query:
            sql += " AND query=?"
            params = (query,)
        with self._connect() as connection:
            return int(connection.execute(sql, params).fetchone()[0])
