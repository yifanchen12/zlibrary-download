from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


SUPPORTED_SUFFIXES = {".epub", ".txt", ".md", ".markdown", ".html", ".htm"}
MAX_DOCUMENT_BYTES = 32 * 1024**2


class ReaderError(ValueError):
    pass


class _TextExtractor(HTMLParser):
    blocks = {"address", "article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag in self.blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(part.split()) for part in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def _decode(data: bytes) -> str:
    encodings = ("utf-16", "utf-8-sig", "gb18030") if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeError:
            pass
    raise ReaderError("文件编码无法识别。")


def _html_text(data: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(_decode(data))
    return parser.text()


def _member(base: PurePosixPath, href: str) -> str:
    path = PurePosixPath(unquote(href.split("#", 1)[0].split("?", 1)[0]))
    resolved = base / path
    if resolved.is_absolute() or ".." in resolved.parts:
        raise ReaderError("EPUB 包含不安全的章节路径。")
    return resolved.as_posix()


def _read_member(archive: ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as error:
        raise ReaderError("EPUB 缺少必要文件。") from error
    if info.file_size > MAX_DOCUMENT_BYTES:
        raise ReaderError("EPUB 章节过大。")
    return archive.read(info)


def _read_epub(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            container = ElementTree.fromstring(_read_member(archive, "META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise ReaderError("EPUB 缺少内容清单。")
            package_name = _member(PurePosixPath(), rootfile.get("full-path", ""))
            package = ElementTree.fromstring(_read_member(archive, package_name))
            base = PurePosixPath(package_name).parent
            manifest = {
                item.get("id", ""): _member(base, item.get("href", ""))
                for item in package.findall(".//{*}manifest/{*}item")
                if item.get("id") and item.get("href")
            }
            names = [manifest.get(item.get("idref", ""), "") for item in package.findall(".//{*}spine/{*}itemref")]
            names = [name for name in names if name]
            if not names:
                raise ReaderError("EPUB 没有可读书脊。")
            chapters: list[str] = []
            total = 0
            for name in names:
                text = _html_text(_read_member(archive, name))
                total += len(text.encode("utf-8"))
                if total > MAX_DOCUMENT_BYTES:
                    raise ReaderError("EPUB 正文超过内置阅读器限制。")
                if text:
                    chapters.append(text)
            return "\n\n".join(chapters)
    except (BadZipFile, ElementTree.ParseError, OSError, RuntimeError) as error:
        raise ReaderError("EPUB 文件损坏或结构无效。") from error


def read_document(path: Path) -> str:
    if not path.is_file():
        raise ReaderError("本地文件不存在。")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ReaderError("此格式请使用系统阅读器。")
    if path.stat().st_size > MAX_DOCUMENT_BYTES and suffix != ".epub":
        raise ReaderError("文件超过内置阅读器 32 MiB 限制。")
    if suffix == ".epub":
        text = _read_epub(path)
    elif suffix in {".html", ".htm"}:
        text = _html_text(path.read_bytes())
    else:
        text = _decode(path.read_bytes())
    if not text.strip():
        raise ReaderError("文件没有可读正文。")
    return text.strip()
