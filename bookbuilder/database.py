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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    source_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT,
                    publisher TEXT,
                    year TEXT,
                    language TEXT,
                    file_format TEXT,
                    expected_bytes INTEGER DEFAULT 0,
                    detail_url TEXT,
                    cover_url TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reading_states (
                    download_id INTEGER PRIMARY KEY,
                    progress REAL NOT NULL DEFAULT 0,
                    last_opened TEXT NOT NULL,
                    open_count INTEGER NOT NULL DEFAULT 1
                )
                """
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

    def download(self, download_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM downloads WHERE id=?", (download_id,)).fetchone()

    def toggle_favorite(self, book: Book) -> bool:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM favorites WHERE source_id=?", (book.source_id,)
            ).fetchone()
            if existing:
                connection.execute("DELETE FROM favorites WHERE source_id=?", (book.source_id,))
                return False
            connection.execute(
                """
                INSERT INTO favorites (
                    source_id, title, author, publisher, year, language,
                    file_format, expected_bytes, detail_url, cover_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    book.cover_url,
                    self._now(),
                ),
            )
            return True

    def is_favorite(self, source_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM favorites WHERE source_id=?", (source_id,)
            ).fetchone() is not None

    def favorites(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(connection.execute("SELECT * FROM favorites ORDER BY created_at DESC").fetchall())

    def record_reading(self, download_id: int, progress: float | None = None) -> None:
        value = None if progress is None else min(1.0, max(0.0, float(progress)))
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM reading_states WHERE download_id=?", (download_id,)).fetchone():
                if value is None:
                    connection.execute(
                        "UPDATE reading_states SET last_opened=?, open_count=open_count+1 WHERE download_id=?",
                        (self._now(), download_id),
                    )
                else:
                    connection.execute(
                        "UPDATE reading_states SET progress=?, last_opened=? WHERE download_id=?",
                        (value, self._now(), download_id),
                    )
            else:
                connection.execute(
                    "INSERT INTO reading_states(download_id, progress, last_opened) VALUES (?, ?, ?)",
                    (download_id, value or 0.0, self._now()),
                )

    def reading_state(self, download_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM reading_states WHERE download_id=?", (download_id,)
            ).fetchone()

    def reading_history(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT r.progress, r.last_opened, r.open_count, d.*
                    FROM reading_states r JOIN downloads d ON d.id=r.download_id
                    WHERE d.status='completed' ORDER BY r.last_opened DESC
                    """
                ).fetchall()
            )
