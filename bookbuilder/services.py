from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from .browser import BrowserController, BrowserError
from .config import Settings
from .database import HistoryDatabase
from .models import BatchOptions, Book, DownloadResult
from .utils import fuzzy_score


EventCallback = Callable[[str, dict[str, object]], None]


class DownloadService:
    def __init__(self, browser: BrowserController, database: HistoryDatabase, settings: Settings) -> None:
        self.browser = browser
        self.database = database
        self.settings = settings

    def download(
        self,
        book: Book,
        output_dir: str,
        query: str,
        progress: Callable[[int, int], None] | None = None,
        skip_existing: bool = True,
    ) -> DownloadResult:
        existing = self.database.completed(book.source_id)
        if skip_existing and existing and existing["local_path"] and Path(existing["local_path"]).is_file():
            return DownloadResult(
                path=str(existing["local_path"]),
                size_bytes=int(existing["actual_bytes"] or 0),
                history_id=int(existing["id"]),
                skipped=True,
            )

        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target).free
        reserve = 512 * 1024**2
        if book.size_bytes and free < book.size_bytes + reserve:
            raise BrowserError("目标磁盘剩余空间不足（程序保留 512 MB 安全余量）。")

        history_id = self.database.begin(book, query)
        try:
            path = self.browser.download(
                book,
                target,
                timeout=self.settings.download_timeout,
                progress=progress,
            )
            actual = path.stat().st_size
            self.database.complete(history_id, str(path), actual)
            return DownloadResult(str(path), actual, history_id)
        except Exception as error:
            self.database.fail(history_id, str(error))
            raise


class LibraryBuilder:
    def __init__(self, browser: BrowserController, downloads: DownloadService) -> None:
        self.browser = browser
        self.downloads = downloads

    def run(
        self,
        options: BatchOptions,
        resume_event: threading.Event,
        cancel_event: threading.Event,
        callback: EventCallback,
    ) -> dict[str, int]:
        scanned = 0
        downloaded = 0
        total_bytes = 0
        seen: set[str] = set()

        for page in range(1, options.max_pages + 1):
            if cancel_event.is_set() or total_bytes >= options.target_bytes:
                break
            while not resume_event.wait(0.25):
                if cancel_event.is_set():
                    break
            if cancel_event.is_set():
                break
            callback("search", {"page": page, "scanned": scanned, "bytes": total_bytes})
            books = self.browser.search(options.query, page)
            if not books:
                break

            for book in books:
                scanned += 1
                if book.source_id in seen:
                    continue
                seen.add(book.source_id)
                book.match_score = fuzzy_score(options.query, book, options.extra_keywords)
                if book.match_score < options.threshold:
                    callback("skip", {"book": book, "reason": f"匹配度 {book.match_score}%"})
                    continue
                if options.preferred_format != "ANY" and options.preferred_format not in book.file_format:
                    callback("skip", {"book": book, "reason": f"格式 {book.file_format or '未知'}"})
                    continue
                remaining = options.target_bytes - total_bytes
                if book.size_bytes <= 0:
                    callback("skip", {"book": book, "reason": "结果未提供文件大小"})
                    continue
                # Search pages round displayed sizes. Keep a guard so the actual file
                # cannot normally push a capacity-limited library over its target.
                size_guard = max(1024**2, int(book.size_bytes * 0.02))
                if book.size_bytes + size_guard > remaining:
                    callback("skip", {"book": book, "reason": "超过剩余容量"})
                    continue
                if cancel_event.is_set():
                    break
                while not resume_event.wait(0.25):
                    if cancel_event.is_set():
                        break
                if cancel_event.is_set():
                    break

                callback("book_start", {"book": book, "bytes": total_bytes})

                def on_progress(current: int, expected: int) -> None:
                    callback(
                        "progress",
                        {"book": book, "current": current, "expected": expected, "bytes": total_bytes},
                    )

                try:
                    result = self.downloads.download(
                        book,
                        options.output_dir,
                        options.query,
                        progress=on_progress,
                        skip_existing=True,
                    )
                    if result.skipped:
                        callback("skip", {"book": book, "reason": "历史记录中已下载"})
                    else:
                        downloaded += 1
                        total_bytes += result.size_bytes
                        callback(
                            "book_done",
                            {"book": book, "result": result, "bytes": total_bytes, "count": downloaded},
                        )
                except BrowserError as error:
                    callback("error", {"book": book, "error": str(error)})
                if cancel_event.wait(self.downloads.settings.request_delay):
                    break

        summary = {"scanned": scanned, "downloaded": downloaded, "bytes": total_bytes}
        callback("done", {**summary, "cancelled": cancel_event.is_set()})
        return summary
