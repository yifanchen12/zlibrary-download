from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from selenium.common.exceptions import WebDriverException

from bookbuilder.browser import AccessCheckError, BrowserController, navigation_error_message
from bookbuilder.config import DEFAULT_BASE_URL, Settings, normalize_base_url
from bookbuilder.database import HistoryDatabase
from bookbuilder.models import Book
from bookbuilder.source_discovery import (
    SourceDiscoveryError,
    discover_preferred_source,
    managed_source_origin,
    preferred_url_from_manifest,
    redirected_managed_source,
    source_check_due,
)
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


class SettingsTests(unittest.TestCase):
    def test_legacy_source_is_migrated(self) -> None:
        self.assertEqual(normalize_base_url("https://z-library.bz/"), DEFAULT_BASE_URL)

    def test_load_migrates_existing_legacy_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_dir = Path(directory) / "AuthorizedBookBuilder"
            app_dir.mkdir()
            (app_dir / "settings.json").write_text(
                json.dumps({"output_dir": directory, "base_url": "https://z-library.bz"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                settings = Settings.load()
            self.assertEqual(settings.base_url, DEFAULT_BASE_URL)

    def test_custom_source_is_preserved(self) -> None:
        self.assertEqual(normalize_base_url("https://books.example/"), "https://books.example")

    def test_search_path_is_normalized_to_origin(self) -> None:
        self.assertEqual(normalize_base_url("https://z-library.biz/s/"), DEFAULT_BASE_URL)

    def test_invalid_browser_mode_falls_back_to_auto(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_dir = Path(directory) / "AuthorizedBookBuilder"
            app_dir.mkdir()
            (app_dir / "settings.json").write_text(
                json.dumps({"output_dir": directory, "browser_mode": "invalid"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                settings = Settings.load()
            self.assertEqual(settings.browser_mode, "auto")


class SourceDiscoveryTests(unittest.TestCase):
    def test_manifest_accepts_managed_https_origin(self) -> None:
        preferred, updated_at = preferred_url_from_manifest(
            {
                "schema_version": 1,
                "updated_at": "2026-09-03",
                "preferred_base_url": "https://z-library.biz/",
            }
        )
        self.assertEqual(preferred, "https://z-library.biz")
        self.assertEqual(updated_at, "2026-09-03")

    def test_manifest_rejects_unrelated_or_insecure_source(self) -> None:
        for value in ("http://z-library.biz", "https://example.com"):
            with self.subTest(value=value), self.assertRaises(SourceDiscoveryError):
                preferred_url_from_manifest({"schema_version": 1, "preferred_base_url": value})

    def test_managed_source_and_redirect_detection(self) -> None:
        self.assertEqual(managed_source_origin("https://z-library.biz/s/?q=test"), "https://z-library.biz")
        self.assertEqual(
            redirected_managed_source("https://z-library.bz", "https://z-library.biz/s/?q=test"),
            "https://z-library.biz",
        )
        self.assertIsNone(redirected_managed_source("https://books.example", "https://z-library.biz"))

    def test_source_check_interval(self) -> None:
        self.assertTrue(source_check_due(0, now=100))
        self.assertFalse(source_check_due(99, now=100))

    @patch("bookbuilder.source_discovery.requests.get")
    def test_remote_registry_updates_managed_source(self, request_get: object) -> None:
        response = request_get.return_value  # type: ignore[attr-defined]
        response.content = b"{}"
        response.json.return_value = {
            "schema_version": 1,
            "updated_at": "2026-09-03",
            "preferred_base_url": "https://z-library.biz",
        }
        result = discover_preferred_source("https://z-library.sk")
        self.assertTrue(result.changed)
        self.assertEqual(result.preferred_url, "https://z-library.biz")
        response.raise_for_status.assert_called_once_with()

    @patch("bookbuilder.source_discovery.requests.get")
    def test_remote_registry_does_not_check_custom_source(self, request_get: object) -> None:
        result = discover_preferred_source("https://books.example")
        self.assertFalse(result.managed_source)
        self.assertFalse(result.changed)
        request_get.assert_not_called()  # type: ignore[attr-defined]


class ParserTests(unittest.TestCase):
    def test_headless_launch_arguments(self) -> None:
        controller = BrowserController(Settings())
        arguments = controller._launch_arguments(
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Temp\AuthorizedBookBuilder\chrome-profile"),
            9222,
            "headless",
        )
        self.assertIn("--headless=new", arguments)
        self.assertIn("--window-size=1440,1200", arguments)
        self.assertNotIn("--start-minimized", arguments)

    def test_compatibility_launch_arguments(self) -> None:
        controller = BrowserController(Settings(browser_mode="compatibility"))
        arguments = controller._launch_arguments(
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Temp\AuthorizedBookBuilder\chrome-profile"),
            9222,
            "compatibility",
        )
        self.assertIn("--window-position=-32000,-32000", arguments)
        self.assertIn("--disable-backgrounding-occluded-windows", arguments)
        self.assertNotIn("--start-minimized", arguments)
        self.assertNotIn("--headless=new", arguments)

    def test_compatibility_mode_requests_hidden_startup(self) -> None:
        controller = BrowserController(Settings(browser_mode="compatibility"))
        startup_info = controller._startup_info("compatibility")
        if os.name == "nt":
            self.assertIsNotNone(startup_info)
            assert startup_info is not None
            self.assertEqual(startup_info.wShowWindow, 0)
        else:
            self.assertIsNone(startup_info)
        self.assertIsNone(controller._startup_info("headless"))

    def test_navigation_timeout_message_is_actionable_and_has_no_stacktrace(self) -> None:
        error = WebDriverException(
            "unknown error: net::ERR_CONNECTION_TIMED_OUT\n"
            "  (Session info: chrome=151.0.7922.174)\nStacktrace:\nchromedriver!GetHandleVerifier"
        )
        message = navigation_error_message("https://example.invalid/s/?q=private-query", error)
        self.assertIn("连接目标站点超时", message)
        self.assertIn("ERR_CONNECTION_TIMED_OUT", message)
        self.assertIn("example.invalid", message)
        self.assertNotIn("private-query", message)
        self.assertNotIn("Stacktrace", message)

    def test_navigation_dns_message(self) -> None:
        error = WebDriverException("unknown error: net::ERR_NAME_NOT_RESOLVED")
        message = navigation_error_message("https://example.invalid", error)
        self.assertIn("域名解析失败", message)

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

    def test_modern_search_card(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "search_modern.html"
        books = BrowserController.parse_search_html(
            fixture.read_text(encoding="utf-8"),
            "https://z-library.biz/s/?q=test",
        )
        self.assertEqual(len(books), 1)
        book = books[0]
        self.assertEqual(book.source_id, "2r09Bq9VKp")
        self.assertEqual(book.title, "人工智能之知识图谱【文字版】")
        self.assertEqual(book.author, "李涓子; 刘佳")
        self.assertEqual(book.publisher, "清华大学出版社")
        self.assertEqual(book.year, "2019")
        self.assertEqual(book.language, "Chinese")
        self.assertEqual(book.file_format, "PDF")
        self.assertEqual(book.size_bytes, int(3.62 * 1024**2))
        self.assertEqual(book.detail_url, "https://z-library.biz/book/2r09Bq9VKp/example.html")

    def test_auto_mode_retries_access_check_in_compatibility_mode(self) -> None:
        fixture = (Path(__file__).parent / "fixtures" / "search_modern.html").read_text(encoding="utf-8")
        controller = BrowserController(Settings(browser_mode="auto"))
        controller.driver = Mock(
            page_source=fixture,
            current_url="https://z-library.biz/s/?q=test",
        )
        with (
            patch.object(controller, "_navigate", side_effect=[AccessCheckError("blocked"), None]) as navigate,
            patch.object(controller, "close") as close,
        ):
            books = controller.search("test")
        self.assertEqual(len(books), 1)
        self.assertEqual(controller.runtime_mode, "compatibility")
        self.assertEqual(navigate.call_count, 2)
        close.assert_called_once_with()


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
