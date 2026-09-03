from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .config import Settings, app_data_dir
from .models import Book
from .source_discovery import redirected_managed_source
from .utils import parse_size, safe_filename, unique_path


class BrowserError(RuntimeError):
    pass


class AccessCheckError(BrowserError):
    pass


_NETWORK_ERROR_MESSAGES = {
    "ERR_CONNECTION_TIMED_OUT": "连接目标站点超时",
    "ERR_NAME_NOT_RESOLVED": "目标站点域名解析失败",
    "ERR_CONNECTION_REFUSED": "目标站点拒绝连接",
    "ERR_INTERNET_DISCONNECTED": "当前设备未连接到网络",
    "ERR_NETWORK_CHANGED": "访问过程中网络连接发生变化",
    "ERR_PROXY_CONNECTION_FAILED": "系统代理连接失败",
    "ERR_TUNNEL_CONNECTION_FAILED": "代理隧道建立失败",
    "ERR_SSL_PROTOCOL_ERROR": "目标站点的 TLS/SSL 连接失败",
    "ERR_CERT_DATE_INVALID": "目标站点证书日期无效",
    "ERR_CERT_AUTHORITY_INVALID": "目标站点证书不受信任",
}


def navigation_error_message(url: str, error: WebDriverException) -> str:
    """Convert Chrome navigation failures into a short actionable message.

    Selenium's default string representation contains a native stack trace. It is
    useful to developers but confusing in the desktop UI, and can include a full
    query URL. Only the origin and the Chrome network error code are surfaced here.
    """

    raw = getattr(error, "msg", "") or str(error)
    host = urlsplit(url).netloc or "设置中的站点入口"
    match = re.search(r"net::(ERR_[A-Z0-9_]+)", raw)
    code = match.group(1) if match else ""
    reason = _NETWORK_ERROR_MESSAGES.get(code, "Chrome 打开目标页面失败")
    code_suffix = f"（{code}）" if code else ""
    return (
        f"{reason}{code_suffix}：{host}\n\n"
        "Chrome 与自动化驱动已经正常启动，但后台浏览器无法访问该站点。请先用普通浏览器测试“设置与授权”中的站点入口；"
        "如果普通浏览器依赖代理或 VPN 扩展，后台独立 Chrome 不会继承该扩展，请改用系统代理或可直连网络后重试。"
    )


def find_chrome() -> Path:
    candidates: list[Path] = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    located = shutil.which("chrome") or shutil.which("chrome.exe")
    if located:
        candidates.insert(0, Path(located))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BrowserError("未找到 Google Chrome。请先安装 Chrome 后重试。")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _bundled_driver() -> Path | None:
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parents[1]]
    for root in roots:
        if not str(root):
            continue
        candidate = root / "drivers" / "chromedriver.exe"
        if candidate.is_file():
            return candidate
    return None


class BrowserController:
    """Launch an isolated Chrome session through Chrome DevTools.

    Automatic mode starts with native ``--headless=new`` and retries in a minimized
    compatibility window only when the source rejects headless Chrome. A dedicated
    profile keeps both modes isolated from the user's personal Chrome profile.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver: webdriver.Chrome | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self._last_request = 0.0
        self.runtime_mode = "compatibility" if settings.browser_mode == "compatibility" else "headless"

    def apply_configured_mode(self) -> None:
        """Restart on the next request using the mode selected in settings."""

        self.close()
        self.runtime_mode = "compatibility" if self.settings.browser_mode == "compatibility" else "headless"

    @staticmethod
    def _launch_arguments(chrome: Path, profile: Path, port: int, mode: str = "headless") -> list[str]:
        arguments = [
            str(chrome),
            "--window-size=1440,1200",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-search-engine-choice-screen",
            "--remote-allow-origins=*",
            "about:blank",
        ]
        if mode == "compatibility":
            arguments.insert(1, "--start-minimized")
        else:
            arguments.insert(1, "--headless=new")
        return arguments

    def start(self) -> None:
        if self.driver:
            return
        chrome = find_chrome()
        profile = app_data_dir() / "chrome-profile"
        profile.mkdir(parents=True, exist_ok=True)
        port = _free_port()
        args = self._launch_arguments(chrome, profile, port, self.runtime_mode)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        endpoint = f"http://127.0.0.1:{port}/json/version"
        for _ in range(60):
            try:
                response = requests.get(endpoint, timeout=1)
                if response.ok:
                    break
            except requests.RequestException:
                pass
            if self.process.poll() is not None:
                raise BrowserError("Chrome 启动失败。")
            time.sleep(0.25)
        else:
            self.close()
            raise BrowserError("无法连接到 Chrome 自动化端口。")

        options = Options()
        options.debugger_address = f"127.0.0.1:{port}"
        driver_path = _bundled_driver()
        try:
            service = Service(executable_path=str(driver_path)) if driver_path else Service()
            self.driver = webdriver.Chrome(service=service, options=options)
        except WebDriverException as first_error:
            if driver_path:
                try:
                    self.driver = webdriver.Chrome(options=options)
                    return
                except WebDriverException:
                    pass
            self.close()
            raise BrowserError(f"ChromeDriver 启动失败：{first_error.msg}") from first_error

    def close(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def _throttle(self) -> None:
        wait = self.settings.request_delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _adopt_redirected_source(self) -> None:
        assert self.driver is not None
        redirected = redirected_managed_source(self.settings.base_url, self.driver.current_url)
        if redirected is None:
            return
        self.settings.base_url = redirected
        self.settings.source_checked_at = time.time()
        self.settings.save()

    def _navigate(self, url: str, selector: str | None = None) -> None:
        self.start()
        assert self.driver is not None
        self._throttle()
        self.driver.set_page_load_timeout(max(20, self.settings.page_timeout))
        try:
            self.driver.get(url)
        except TimeoutException as error:
            try:
                self.driver.execute_script("window.stop();")
            except WebDriverException:
                pass
            host = urlsplit(url).netloc or "设置中的站点入口"
            raise BrowserError(
                f"页面加载超过 {max(20, self.settings.page_timeout)} 秒：{host}\n\n"
                "请先用普通浏览器测试站点入口，并检查当前网络、系统代理或 VPN 状态。"
            ) from error
        except WebDriverException as error:
            raise BrowserError(navigation_error_message(url, error)) from error
        self._adopt_redirected_source()

        def ready(driver: webdriver.Chrome) -> bool:
            html = driver.page_source
            lowered = html.lower()
            if "try again later or contact us" in lowered:
                return True
            if selector and driver.find_elements(By.CSS_SELECTOR, selector):
                return True
            return (
                driver.execute_script("return document.readyState") == "complete"
                and len(html) > 15_000
                and "checking your browser" not in lowered
                and "wait a moment, checking" not in lowered
            )

        try:
            WebDriverWait(self.driver, self.settings.page_timeout, poll_frequency=1).until(ready)
        except TimeoutException as error:
            raise BrowserError(
                "页面已打开，但在等待时间内未发现可解析的内容。站点可能正在进行访问检查、页面结构已经变化，或当前网络响应过慢。"
            ) from error
        except WebDriverException as error:
            raise BrowserError(navigation_error_message(url, error)) from error
        if "try again later or contact us" in self.driver.page_source.lower():
            raise AccessCheckError(
                "站点访问检查未通过。自动兼容模式会改用最小化的普通 Chrome 重试；若仍失败，请稍后重试或更换网络节点。"
            )

    def search(self, query: str, page: int = 1) -> list[Book]:
        params = f"q={quote_plus(query)}"
        if page > 1:
            params += f"&page={page}"
        url = f"{self.settings.base_url.rstrip('/')}/s/?{params}"
        try:
            self._navigate(url, ".resItemBoxBooks")
        except AccessCheckError:
            if self.settings.browser_mode != "auto" or self.runtime_mode == "compatibility":
                raise
            self.close()
            self.runtime_mode = "compatibility"
            self._navigate(url, ".resItemBoxBooks")
        assert self.driver is not None
        return self.parse_search_html(self.driver.page_source, self.driver.current_url)

    @staticmethod
    def parse_search_html(html: str, base_url: str = "") -> list[Book]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Book] = []
        for card in soup.select(".resItemBoxBooks"):
            component = card.select_one("z-bookcard")
            title_node = card.select_one(".book-title a") or card.select_one('z-bookcard [slot="title"]')
            if not title_node:
                continue
            detail_url = card.get("data-url") or title_node.get("href") or (component.get("href") if component else "") or ""
            detail_url = urljoin(base_url, detail_url) if base_url else detail_url
            identifier = re.search(r"/book/([^/]+)", detail_url)
            if not identifier:
                continue
            metadata: dict[str, str] = {}
            for item in card.select(".book-meta-bottom .meta-item"):
                label = item.select_one(".meta-label")
                key = label.get_text(" ", strip=True).rstrip(":").casefold() if label else ""
                if label:
                    label.extract()
                metadata[key] = " ".join(item.get_text(" ", strip=True).split())
            file_text = component.get("filesize", "") if component else metadata.get("file", "")
            if component:
                file_format = component.get("extension", "").strip().upper()
            else:
                file_format = file_text.split(",", 1)[0].strip().upper() if file_text else ""
            cover = card.select_one(".b-cover img") or card.select_one("z-bookcard img")
            cover_url = (cover.get("src") or cover.get("data-src") or "") if cover else ""
            if base_url and cover_url:
                cover_url = urljoin(base_url, cover_url)
            author_node = card.select_one(".book-author") or card.select_one('z-bookcard [slot="author"]')
            publisher = component.get("publisher", "") if component else ""
            if not publisher:
                publisher_node = card.select_one(".book-publisher")
                publisher = publisher_node.get_text(" ", strip=True) if publisher_node else ""
            results.append(
                Book(
                    source_id=identifier.group(1),
                    title=" ".join(title_node.get_text(" ", strip=True).split()),
                    author=" ".join(author_node.get_text(" ", strip=True).split()) if author_node else "",
                    publisher=" ".join(publisher.split()),
                    year=component.get("year", "") if component else metadata.get("year", ""),
                    language=component.get("language", "") if component else metadata.get("language", ""),
                    file_format=file_format,
                    size_bytes=parse_size(file_text),
                    detail_url=detail_url,
                    cover_url=cover_url,
                )
            )
        return results

    def download(
        self,
        book: Book,
        output_dir: Path,
        timeout: int,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._navigate(book.detail_url, "a.addDownloadedBook[href]")
        assert self.driver is not None
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "a.addDownloadedBook[href]")
        if not buttons:
            raise BrowserError("详情页未找到可用下载按钮。")
        button = buttons[0]
        button_text = button.text.upper()
        if book.file_format and book.file_format not in button_text:
            matching = [item for item in buttons if book.file_format in item.text.upper()]
            if matching:
                button = matching[0]

        self.driver.execute_cdp_cmd(
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(output_dir.resolve()), "eventsEnabled": True},
        )
        before = {path.resolve(): (path.stat().st_size, path.stat().st_mtime_ns) for path in output_dir.iterdir() if path.is_file()}
        started_at = time.time()
        self.driver.execute_script("arguments[0].click()", button)
        last_size = -1
        completed: Path | None = None

        while time.time() - started_at < timeout:
            time.sleep(0.5)
            files = [path for path in output_dir.iterdir() if path.is_file()]
            partials = [path for path in files if path.name.lower().endswith((".crdownload", ".tmp"))]
            candidates: list[Path] = []
            for path in files:
                if path in partials:
                    continue
                resolved = path.resolve()
                old = before.get(resolved)
                stat = path.stat()
                if old is None or stat.st_mtime_ns != old[1] or stat.st_size != old[0]:
                    candidates.append(path)
            current = max((path.stat().st_size for path in partials), default=0)
            if candidates and not partials:
                completed = max(candidates, key=lambda item: item.stat().st_mtime_ns)
                current = completed.stat().st_size
            if progress and current != last_size:
                progress(current, book.size_bytes)
                last_size = current
            if completed:
                break
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.casefold()
            if "download limit" in page_text or "daily limit" in page_text:
                raise BrowserError("站点提示已达到下载限额。")
        if not completed:
            raise BrowserError("等待文件下载完成超时。")

        suffix = completed.suffix or (f".{book.file_format.casefold()}" if book.file_format else "")
        stem = safe_filename(f"{book.title} - {book.author}".strip(" -"), book.source_id)
        destination = unique_path(output_dir, stem, suffix)
        if completed.resolve() != destination.resolve():
            completed.replace(destination)
        return destination
