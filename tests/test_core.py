from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bookbuilder.browser import BrowserController
from bookbuilder.database import HistoryDatabase
from bookbuilder.models import Book
from bookbuilder.utils import fuzzy_score, human_size, parse_size, safe_filename, split_keywords


def sample_book(**changes: object) -> Book:
    values: dict[str, object] = {
        "source_id": "ABC123",
        "title": "人工智能导论",
        "author": "张三",
        "publisher": "示例出版社",
        "year": "2025",
        "language": "Chinese",
        "file_format": "PDF",
        "size_bytes": 1024,
        "detail_url": "https://example.invalid/book/ABC123/example.html",
    }
    values.update(changes)
    return Book(**values)  # type: ignore[arg-type]


class UtilityTests(unittest.TestCase):
    def test_size_parsing_and_display(self) -> None:
        self.assertEqual(parse_size("PDF, 53.97 MB"), int(53.97 * 1024**2))
        self.assertEqual(parse_size("EPUB, 398 KB"), 398 * 1024)
        self.assertEqual(parse_size("unknown"), 0)
        self.assertEqual(human_size(1024**3), "1.00 GB")

    def test_safe_filename(self) -> None:
        self.assertEqual(safe_filename('A:B/C*D?'), "A_B_C_D_")

    def test_fuzzy_matching(self) -> None:
        book = sample_book()
        self.assertEqual(fuzzy_score("人工智能导论", book), 100)
        self.assertGreaterEqual(fuzzy_score("人工智能", book), 80)
        score = fuzzy_score("人工智能", book, split_keywords("教材, 导论"))
        self.assertGreaterEqual(score, 70)
        self.assertLess(fuzzy_score("园艺", book), 30)


class ParserTests(unittest.TestCase):
    def test_search_card(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "search.html"
        books = BrowserController.parse_search_html(fixture.read_text(encoding="utf-8"))
        self.assertEqual(len(books), 1)
        book = books[0]
        self.assertEqual(book.source_id, "ABC123")
        self.assertEqual(book.title, "人工智能导论")
        self.assertEqual(book.author, "张三")
        self.assertEqual(book.file_format, "PDF")
        self.assertEqual(book.size_bytes, int(53.97 * 1024**2))


class DatabaseTests(unittest.TestCase):
    def test_history_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = HistoryDatabase(Path(directory) / "history.sqlite3")
            book = sample_book()
            history_id = database.begin(book, "人工智能")
            self.assertIsNone(database.completed(book.source_id))
            target = Path(directory) / "book.pdf"
            target.write_bytes(b"pdf")
            database.complete(history_id, str(target), target.stat().st_size)
            row = database.completed(book.source_id)
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["actual_bytes"], 3)
            self.assertEqual(database.completed_total("人工智能"), 3)

    def test_failed_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = HistoryDatabase(Path(directory) / "history.sqlite3")
            history_id = database.begin(sample_book(), "test")
            database.fail(history_id, "network error")
            row = database.recent(1)[0]
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["error"], "network error")


if __name__ == "__main__":
    unittest.main()

