from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .browser import BrowserController, BrowserError
from .config import Settings, normalize_base_url
from .database import HistoryDatabase
from .models import BatchOptions, Book
from .services import DownloadService, LibraryBuilder
from .utils import human_size, split_keywords


PALETTE = {
    "navy": "#071A3A",
    "deep_blue": "#0B367D",
    "blue": "#1677FF",
    "blue_hover": "#0C62DE",
    "cyan": "#54D6FF",
    "ice": "#EAF4FF",
    "pale": "#F4F9FF",
    "surface": "#FFFFFF",
    "border": "#B9D9FF",
    "text": "#102A4C",
    "muted": "#607B9E",
    "danger": "#E05272",
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative


class BookBuilderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = Settings.load()
        self.database = HistoryDatabase()
        self.browser = BrowserController(self.settings)
        self.downloads = DownloadService(self.browser, self.database, self.settings)
        self.builder = LibraryBuilder(self.browser, self.downloads)
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy_lock = threading.Lock()
        self.search_results: dict[str, Book] = {}
        self.resume_event = threading.Event()
        self.resume_event.set()
        self.cancel_event = threading.Event()

        self.root.title("授权书籍下载与模糊建库工具")
        self.root.geometry("1240x880")
        self.root.minsize(1040, 700)
        self.root.configure(background=PALETTE["ice"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_style()
        self._build_ui()
        self._load_history()
        self.root.after(100, self._process_messages)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        font = ("Microsoft YaHei UI", 9)
        style.configure(".", font=font, background=PALETTE["surface"], foreground=PALETTE["text"])
        style.configure("TFrame", background=PALETTE["surface"])
        style.configure("App.TFrame", background=PALETTE["ice"])
        style.configure("TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
        style.configure("Hint.TLabel", foreground=PALETTE["muted"], font=("Microsoft YaHei UI", 9))
        style.configure(
            "TLabelFrame",
            background=PALETTE["surface"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "TLabelFrame.Label",
            background=PALETTE["surface"],
            foreground=PALETTE["deep_blue"],
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(4, 0),
        )
        style.configure(
            "TNotebook",
            background=PALETTE["ice"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background="#DCEBFF",
            foreground=PALETTE["muted"],
            padding=(22, 10),
            borderwidth=0,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PALETTE["surface"]), ("active", "#CDE4FF")],
            foreground=[("selected", PALETTE["blue"]), ("active", PALETTE["deep_blue"])],
        )
        style.configure(
            "TButton",
            background="#E4F0FF",
            foreground=PALETTE["deep_blue"],
            bordercolor="#C2DFFF",
            lightcolor="#C2DFFF",
            darkcolor="#C2DFFF",
            borderwidth=1,
            padding=(13, 7),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", "#CFE5FF"), ("pressed", "#B7D7FF"), ("disabled", "#EDF3FA")],
            foreground=[("disabled", "#9AAFC7")],
        )
        style.configure(
            "Accent.TButton",
            background=PALETTE["blue"],
            foreground="#FFFFFF",
            bordercolor=PALETTE["blue"],
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(16, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("active", PALETTE["blue_hover"]), ("pressed", "#084CA9"), ("disabled", "#A8C9EE")],
            foreground=[("disabled", "#F3F7FC")],
        )
        style.configure(
            "Danger.TButton",
            background="#FFE8EE",
            foreground="#B82D52",
            bordercolor="#FFC5D4",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#FFD4DF"), ("pressed", "#FFB7C9")])
        style.configure(
            "TEntry",
            fieldbackground=PALETTE["pale"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            insertcolor=PALETTE["blue"],
            padding=(8, 7),
        )
        style.map("TEntry", bordercolor=[("focus", PALETTE["blue"])], lightcolor=[("focus", PALETTE["blue"])])
        style.configure("TSpinbox", fieldbackground=PALETTE["pale"], bordercolor=PALETTE["border"], padding=5)
        style.configure("TCombobox", fieldbackground=PALETTE["pale"], bordercolor=PALETTE["border"], padding=5)
        style.configure(
            "Treeview",
            rowheight=31,
            font=("Microsoft YaHei UI", 9),
            background=PALETTE["surface"],
            fieldbackground=PALETTE["surface"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            borderwidth=1,
        )
        style.map("Treeview", background=[("selected", "#B8DDFF")], foreground=[("selected", PALETTE["navy"])])
        style.configure(
            "Treeview.Heading",
            font=("Microsoft YaHei UI", 9, "bold"),
            background="#DCEEFF",
            foreground=PALETTE["deep_blue"],
            bordercolor=PALETTE["border"],
            padding=(6, 7),
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#C8E4FF")])
        style.configure(
            "Horizontal.TProgressbar",
            background=PALETTE["blue"],
            troughcolor="#DDEEFF",
            bordercolor="#DDEEFF",
            lightcolor=PALETTE["cyan"],
            darkcolor=PALETTE["blue"],
            thickness=10,
        )
        style.configure(
            "Status.TLabel",
            background=PALETTE["navy"],
            foreground="#D9F3FF",
            font=("Microsoft YaHei UI", 9),
            padding=(12, 6),
        )
        style.configure("TCheckbutton", background=PALETTE["surface"], foreground=PALETTE["text"], padding=3)

    def _draw_header(self, event: tk.Event | None = None) -> None:
        canvas = self.header
        width = max(canvas.winfo_width(), 1040)
        height = 148
        canvas.delete("all")
        start = (7, 26, 58)
        end = (15, 70, 145)
        bands = 28
        for index in range(bands):
            ratio = index / max(1, bands - 1)
            color = "#%02x%02x%02x" % tuple(int(a + (b - a) * ratio) for a, b in zip(start, end, strict=True))
            left = int(width * index / bands)
            right = int(width * (index + 1) / bands) + 1
            canvas.create_rectangle(left, 0, right, height, fill=color, outline="")
        for x in range(20, width, 92):
            canvas.create_line(x, 0, x + 54, height, fill="#1A5596", width=1)
        canvas.create_line(0, height - 3, width, height - 3, fill=PALETTE["cyan"], width=2)
        canvas.create_oval(26, 25, 34, 33, fill=PALETTE["cyan"], outline="")
        canvas.create_line(34, 29, 145, 29, fill="#3D8ED0", width=1)
        canvas.create_text(
            30,
            45,
            anchor="w",
            text="FONTAINE LIBRARY NODE  //  ONLINE",
            fill="#8DE7FF",
            font=("Consolas", 9, "bold"),
        )
        canvas.create_text(
            30,
            79,
            anchor="w",
            text="授权书籍下载与模糊建库工具",
            fill="#FFFFFF",
            font=("Microsoft YaHei UI", 21, "bold"),
        )
        canvas.create_text(
            32,
            116,
            anchor="w",
            text="SEARCH  /  DOWNLOAD  /  INDEX  /  ARCHIVE",
            fill="#B7DFFF",
            font=("Consolas", 10),
        )
        canvas.create_text(
            width - 170,
            43,
            anchor="e",
            text="HYDRO ARCHIVE\nSYSTEM READY",
            justify="right",
            fill="#74DFFF",
            font=("Consolas", 9, "bold"),
        )
        canvas.create_image(width - 26, 73, image=self.furina_image, anchor="e")

    def _build_ui(self) -> None:
        self.furina_image = tk.PhotoImage(file=str(resource_path("assets/furina_header.png")))
        self.header = tk.Canvas(self.root, height=148, highlightthickness=0, borderwidth=0, background=PALETTE["navy"])
        self.header.pack(fill="x")
        self.header.bind("<Configure>", self._draw_header)
        self._draw_header()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(12, 12))
        self.search_tab = ttk.Frame(self.notebook, padding=12)
        self.batch_tab = ttk.Frame(self.notebook, padding=12)
        self.history_tab = ttk.Frame(self.notebook, padding=12)
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.search_tab, text="检索下载")
        self.notebook.add(self.batch_tab, text="模糊建库")
        self.notebook.add(self.history_tab, text="下载历史")
        self.notebook.add(self.settings_tab, text="设置与授权")
        self._build_search_tab()
        self._build_batch_tab()
        self._build_history_tab()
        self._build_settings_tab()

        self.global_status = tk.StringVar(value="就绪；后台浏览器首次访问详情页时，站点校验可能需要十余秒。")
        ttk.Label(self.root, textvariable=self.global_status, anchor="w", style="Status.TLabel").pack(fill="x", side="bottom")

    @staticmethod
    def _directory_row(parent: ttk.Frame, variable: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text="保存目录").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, columnspan=5, sticky="ew", pady=5)

        def choose() -> None:
            selected = filedialog.askdirectory(initialdir=variable.get() or str(Path.home()))
            if selected:
                variable.set(selected)

        ttk.Button(parent, text="选择目录", command=choose).grid(row=row, column=6, padx=(8, 0), pady=5)

    def _build_search_tab(self) -> None:
        controls = ttk.LabelFrame(self.search_tab, text="检索控制台", padding=14)
        controls.pack(fill="x")
        controls.columnconfigure(1, weight=1)
        self.search_query = tk.StringVar()
        self.search_page = tk.IntVar(value=1)
        self.search_output = tk.StringVar(value=self.settings.output_dir)
        ttk.Label(controls, text="检索词").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        entry = ttk.Entry(controls, textvariable=self.search_query)
        entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=5)
        entry.bind("<Return>", lambda _event: self._start_search())
        ttk.Label(controls, text="页码").grid(row=0, column=4, padx=(12, 4))
        ttk.Spinbox(controls, from_=1, to=500, width=7, textvariable=self.search_page).grid(row=0, column=5)
        self.search_button = ttk.Button(controls, text="开始检索", style="Accent.TButton", command=self._start_search)
        self.search_button.grid(row=0, column=6, padx=(8, 0))
        self._directory_row(controls, self.search_output, 1)

        table_frame = ttk.Frame(self.search_tab)
        table_frame.pack(fill="both", expand=True, pady=(10, 8))
        columns = ("title", "author", "publisher", "year", "language", "format", "size")
        self.search_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.search_tree.tag_configure("odd", background=PALETTE["pale"])
        headings = {
            "title": ("书名", 260),
            "author": ("作者", 150),
            "publisher": ("出版社", 170),
            "year": ("年份", 60),
            "language": ("语言", 90),
            "format": ("格式", 65),
            "size": ("大小", 85),
        }
        for key, (label, width) in headings.items():
            self.search_tree.heading(key, text=label)
            self.search_tree.column(key, width=width, minwidth=50, stretch=key in {"title", "author", "publisher"})
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.search_tree.yview)
        self.search_tree.configure(yscrollcommand=scrollbar.set)
        self.search_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.search_tree.bind("<Double-1>", lambda _event: self._download_selected())

        actions = ttk.Frame(self.search_tab)
        actions.pack(fill="x")
        ttk.Button(actions, text="下载选中项", style="Accent.TButton", command=self._download_selected).pack(side="left")
        ttk.Button(actions, text="打开详情页", command=self._open_selected_source).pack(side="left", padx=8)
        self.search_progress = ttk.Progressbar(actions, length=280, mode="determinate")
        self.search_progress.pack(side="right")
        self.search_status = tk.StringVar(value="等待检索")
        ttk.Label(actions, textvariable=self.search_status).pack(side="right", padx=10)

    def _build_batch_tab(self) -> None:
        form = ttk.LabelFrame(self.batch_tab, text="智能建库参数", padding=14)
        form.pack(fill="x")
        for column in (1, 3, 5):
            form.columnconfigure(column, weight=1)
        self.batch_query = tk.StringVar(value="人工智能")
        self.batch_extra = tk.StringVar(value="教材, 导论, 基础, undergraduate, textbook")
        self.batch_threshold = tk.IntVar(value=55)
        self.batch_target_gb = tk.DoubleVar(value=1.0)
        self.batch_pages = tk.IntVar(value=20)
        self.batch_format = tk.StringVar(value="PDF")
        self.batch_output = tk.StringVar(value=self.settings.output_dir)

        ttk.Label(form, text="主题 / 检索词").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(form, textvariable=self.batch_query).grid(row=0, column=1, columnspan=3, sticky="ew", pady=5)
        ttk.Label(form, text="目标格式").grid(row=0, column=4, padx=(12, 5))
        ttk.Combobox(form, textvariable=self.batch_format, values=("ANY", "PDF", "EPUB"), width=9, state="readonly").grid(
            row=0, column=5, sticky="w"
        )
        ttk.Label(form, text="附加匹配词").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(form, textvariable=self.batch_extra).grid(row=1, column=1, columnspan=5, sticky="ew", pady=5)
        ttk.Label(form, text="模糊匹配阈值").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=5)
        scale = ttk.Scale(form, from_=0, to=100, variable=self.batch_threshold, orient="horizontal")
        scale.grid(row=2, column=1, sticky="ew")
        ttk.Label(form, textvariable=self.batch_threshold, width=4).grid(row=2, column=2, sticky="w")
        ttk.Label(form, text="建库容量（磁盘 GB）").grid(row=2, column=3, sticky="e", padx=(12, 5))
        ttk.Spinbox(form, from_=0.01, to=2048, increment=0.25, textvariable=self.batch_target_gb, width=10).grid(
            row=2, column=4, sticky="w"
        )
        ttk.Label(form, text="最多检索页").grid(row=2, column=5, sticky="e", padx=(12, 5))
        ttk.Spinbox(form, from_=1, to=500, textvariable=self.batch_pages, width=8).grid(row=2, column=6, sticky="w")
        self._directory_row(form, self.batch_output, 3)

        actions = ttk.Frame(self.batch_tab)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="开始建库", style="Accent.TButton", command=self._start_batch).pack(side="left")
        self.pause_button = ttk.Button(actions, text="暂停", command=self._toggle_pause, state="disabled")
        self.pause_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="停止", style="Danger.TButton", command=self._stop_batch, state="disabled")
        self.stop_button.pack(side="left")
        self.batch_summary = tk.StringVar(value="尚未开始")
        ttk.Label(actions, textvariable=self.batch_summary).pack(side="right")

        self.batch_progress = ttk.Progressbar(self.batch_tab, mode="determinate")
        self.batch_progress.pack(fill="x", pady=(0, 8))
        log_frame = ttk.Frame(self.batch_tab)
        log_frame.pack(fill="both", expand=True)
        self.batch_log = tk.Text(
            log_frame,
            height=18,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            background=PALETTE["navy"],
            foreground="#BFEAFF",
            insertbackground=PALETTE["cyan"],
            selectbackground=PALETTE["deep_blue"],
            selectforeground="#FFFFFF",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#2A70B7",
            padx=12,
            pady=10,
        )
        log_scroll = ttk.Scrollbar(log_frame, command=self.batch_log.yview)
        self.batch_log.configure(yscrollcommand=log_scroll.set)
        self.batch_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _build_history_tab(self) -> None:
        actions = ttk.Frame(self.history_tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="刷新", command=self._load_history).pack(side="left")
        ttk.Button(actions, text="打开文件", style="Accent.TButton", command=self._open_history_file).pack(side="left", padx=8)
        ttk.Button(actions, text="打开所在目录", command=self._open_history_folder).pack(side="left")
        columns = ("time", "status", "title", "author", "format", "size", "path", "error")
        self.history_tree = ttk.Treeview(self.history_tab, columns=columns, show="headings", selectmode="browse")
        self.history_tree.tag_configure("odd", background=PALETTE["pale"])
        widths = (145, 80, 220, 120, 60, 85, 280, 180)
        labels = ("时间", "状态", "书名", "作者", "格式", "大小", "本地路径", "错误")
        for key, width, label in zip(columns, widths, labels, strict=True):
            self.history_tree.heading(key, text=label)
            self.history_tree.column(key, width=width, stretch=key in {"title", "path", "error"})
        history_scroll = ttk.Scrollbar(self.history_tab, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=history_scroll.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        history_scroll.pack(side="right", fill="y")

    def _build_settings_tab(self) -> None:
        frame = ttk.LabelFrame(self.settings_tab, text="运行设置与授权", padding=16)
        frame.pack(fill="x")
        frame.columnconfigure(1, weight=1)
        self.setting_output = tk.StringVar(value=self.settings.output_dir)
        self.setting_base = tk.StringVar(value=self.settings.base_url)
        self.setting_delay = tk.DoubleVar(value=self.settings.request_delay)
        self.setting_page_timeout = tk.IntVar(value=self.settings.page_timeout)
        self.setting_download_timeout = tk.IntVar(value=self.settings.download_timeout)
        self.setting_authorized = tk.BooleanVar(value=self.settings.authorization_confirmed)
        labels = (
            ("默认下载目录", self.setting_output),
            ("站点入口", self.setting_base),
            ("请求间隔（秒）", self.setting_delay),
            ("页面超时（秒）", self.setting_page_timeout),
            ("单文件超时（秒）", self.setting_download_timeout),
        )
        for row, (label, variable) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
            ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Checkbutton(
            frame,
            text="我确认仅下载已获授权、开放许可或公版内容，并遵守来源站点规则",
            variable=self.setting_authorized,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(frame, text="保存设置", style="Accent.TButton", command=self._save_settings).grid(
            row=6, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Label(
            self.settings_tab,
            text="说明：Chrome 始终以无窗口后台模式运行；程序只启用一个下载任务，“暂停”会在当前文件完成后生效。历史数据库和浏览器专用配置位于本机 LocalAppData。",
            style="Hint.TLabel",
            wraplength=900,
        ).pack(anchor="w", pady=14)

    def _post(self, event: str, payload: object = None) -> None:
        self.messages.put((event, payload))

    def _run_worker(self, label: str, operation: callable) -> bool:
        if not self.busy_lock.acquire(blocking=False):
            messagebox.showinfo("任务进行中", "请先等待当前检索或下载任务完成。")
            return False

        def target() -> None:
            try:
                operation()
            except Exception as error:
                self._post("worker_error", (label, str(error), traceback.format_exc()))
            finally:
                self.busy_lock.release()
                self._post("worker_idle", label)

        threading.Thread(target=target, name=f"bookbuilder-{label}", daemon=True).start()
        return True

    def _ensure_authorized(self) -> bool:
        if self.settings.authorization_confirmed:
            return True
        confirmed = messagebox.askyesno(
            "授权确认",
            "请确认你只会下载已获授权、开放许可或公版内容，并遵守来源站点规则。\n\n是否确认？",
        )
        if confirmed:
            self.settings.authorization_confirmed = True
            self.setting_authorized.set(True)
            self.settings.save()
        return confirmed

    def _start_search(self) -> None:
        query = self.search_query.get().strip()
        if not query:
            messagebox.showwarning("缺少检索词", "请输入书名或 ISBN。")
            return
        page = max(1, self.search_page.get())
        self.search_button.configure(state="disabled")
        self.search_status.set("正在启动后台浏览器并检索…")

        def operation() -> None:
            books = self.browser.search(query, page)
            self._post("search_done", books)

        if not self._run_worker("search", operation):
            self.search_button.configure(state="normal")

    def _selected_book(self) -> Book | None:
        selected = self.search_tree.selection()
        return self.search_results.get(selected[0]) if selected else None

    def _download_selected(self) -> None:
        book = self._selected_book()
        if not book:
            messagebox.showinfo("未选择", "请先选择一条检索结果。")
            return
        if not self._ensure_authorized():
            return
        output = self.search_output.get().strip()
        if not output:
            messagebox.showwarning("缺少目录", "请选择保存目录。")
            return
        self.search_status.set(f"准备下载：{book.title}")

        def progress(current: int, total: int) -> None:
            self._post("single_progress", (current, total, book.title))

        def operation() -> None:
            result = self.downloads.download(book, output, self.search_query.get().strip(), progress=progress)
            self._post("single_done", (book, result))

        self._run_worker("download", operation)

    def _open_selected_source(self) -> None:
        book = self._selected_book()
        if book:
            webbrowser.open(book.detail_url)

    def _start_batch(self) -> None:
        if not self._ensure_authorized():
            return
        query = self.batch_query.get().strip()
        output = self.batch_output.get().strip()
        try:
            target_bytes = int(float(self.batch_target_gb.get()) * 1024**3)
            pages = int(self.batch_pages.get())
            threshold = int(self.batch_threshold.get())
        except (ValueError, tk.TclError):
            messagebox.showwarning("参数错误", "容量、页数和匹配阈值必须是有效数字。")
            return
        if not query or not output or target_bytes <= 0 or pages <= 0:
            messagebox.showwarning("参数不完整", "请填写主题、目录、正容量和正页数。")
            return
        options = BatchOptions(
            query=query,
            extra_keywords=split_keywords(self.batch_extra.get()),
            threshold=max(0, min(100, threshold)),
            target_bytes=target_bytes,
            max_pages=pages,
            output_dir=output,
            preferred_format=self.batch_format.get(),
        )
        self.cancel_event.clear()
        self.resume_event.set()
        self.pause_button.configure(state="normal", text="暂停")
        self.stop_button.configure(state="normal")
        self.batch_log.configure(state="normal")
        self.batch_log.delete("1.0", "end")
        self.batch_log.configure(state="disabled")
        self.batch_progress.configure(value=0, maximum=max(1, target_bytes))
        self._batch_target_bytes = target_bytes
        self._append_log(f"开始：{query}；阈值 {options.threshold}%；目标 {human_size(target_bytes)}")

        def callback(event: str, payload: dict[str, object]) -> None:
            self._post("batch_event", (event, payload))

        def operation() -> None:
            self.builder.run(options, self.resume_event, self.cancel_event, callback)

        if not self._run_worker("batch", operation):
            self.pause_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")

    def _toggle_pause(self) -> None:
        if self.resume_event.is_set():
            self.resume_event.clear()
            self.pause_button.configure(text="继续")
            self._append_log("已请求暂停；当前文件会先完成。")
        else:
            self.resume_event.set()
            self.pause_button.configure(text="暂停")
            self._append_log("继续建库。")

    def _stop_batch(self) -> None:
        self.cancel_event.set()
        self.resume_event.set()
        self._append_log("已请求停止；当前文件会先完成。")

    def _append_log(self, text: str) -> None:
        self.batch_log.configure(state="normal")
        self.batch_log.insert("end", text + "\n")
        self.batch_log.see("end")
        self.batch_log.configure(state="disabled")

    def _handle_batch_event(self, event: str, payload: dict[str, object]) -> None:
        if event == "search":
            self._append_log(f"检索第 {payload['page']} 页；已扫描 {payload['scanned']} 条")
        elif event == "book_start":
            book = payload["book"]
            assert isinstance(book, Book)
            self._append_log(f"下载：{book.title} [{book.file_format}, {human_size(book.size_bytes)}, {book.match_score}%]")
        elif event == "progress":
            base = int(payload["bytes"])
            current = int(payload["current"])
            self.batch_progress.configure(value=min(self._batch_target_bytes, base + current))
        elif event == "book_done":
            book = payload["book"]
            assert isinstance(book, Book)
            total = int(payload["bytes"])
            self.batch_progress.configure(value=min(self._batch_target_bytes, total))
            self.batch_summary.set(f"{payload['count']} 本 · {human_size(total)}")
            self._append_log(f"完成：{book.title}；累计 {human_size(total)}")
            self._load_history()
        elif event == "error":
            book = payload["book"]
            assert isinstance(book, Book)
            self._append_log(f"错误：{book.title} — {payload['error']}")
        elif event == "done":
            self.pause_button.configure(state="disabled", text="暂停")
            self.stop_button.configure(state="disabled")
            suffix = "（用户停止）" if payload.get("cancelled") else ""
            self.batch_summary.set(
                f"完成{suffix}：扫描 {payload['scanned']}，下载 {payload['downloaded']}，{human_size(int(payload['bytes']))}"
            )
            self._append_log(self.batch_summary.get())

    def _load_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for index, row in enumerate(self.database.recent()):
            size = int(row["actual_bytes"] or row["expected_bytes"] or 0)
            self.history_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                tags=("odd",) if index % 2 else (),
                values=(
                    row["completed_at"] or row["started_at"],
                    row["status"],
                    row["title"],
                    row["author"],
                    row["file_format"],
                    human_size(size),
                    row["local_path"] or "",
                    row["error"] or "",
                ),
            )

    def _history_path(self) -> Path | None:
        selected = self.history_tree.selection()
        if not selected:
            return None
        values = self.history_tree.item(selected[0], "values")
        return Path(values[6]) if len(values) > 6 and values[6] else None

    def _open_history_file(self) -> None:
        path = self._history_path()
        if path and path.is_file():
            os.startfile(path)
        else:
            messagebox.showinfo("文件不存在", "所选记录没有可用的本地文件。")

    def _open_history_folder(self) -> None:
        path = self._history_path()
        if path and path.parent.is_dir():
            os.startfile(path.parent)
        else:
            messagebox.showinfo("目录不存在", "所选记录没有可用的本地目录。")

    def _save_settings(self) -> None:
        try:
            delay = max(1.0, float(self.setting_delay.get()))
            page_timeout = max(20, int(self.setting_page_timeout.get()))
            download_timeout = max(60, int(self.setting_download_timeout.get()))
        except (ValueError, tk.TclError):
            messagebox.showwarning("参数错误", "间隔和超时必须为有效数字。")
            return
        self.settings.output_dir = self.setting_output.get().strip() or self.settings.output_dir
        self.settings.base_url = normalize_base_url(self.setting_base.get())
        self.setting_base.set(self.settings.base_url)
        self.settings.request_delay = delay
        self.settings.page_timeout = page_timeout
        self.settings.download_timeout = download_timeout
        self.settings.authorization_confirmed = bool(self.setting_authorized.get())
        self.settings.save()
        self.search_output.set(self.settings.output_dir)
        self.batch_output.set(self.settings.output_dir)
        messagebox.showinfo("已保存", "设置已保存。Chrome 将继续以无窗口后台模式运行。")

    def _process_messages(self) -> None:
        try:
            while True:
                event, payload = self.messages.get_nowait()
                if event == "search_done":
                    books = payload
                    assert isinstance(books, list)
                    self.search_results.clear()
                    for item in self.search_tree.get_children():
                        self.search_tree.delete(item)
                    for index, book in enumerate(books):
                        iid = f"book-{index}"
                        self.search_results[iid] = book
                        self.search_tree.insert(
                            "",
                            "end",
                            iid=iid,
                            tags=("odd",) if index % 2 else (),
                            values=(book.title, book.author, book.publisher, book.year, book.language, book.file_format, human_size(book.size_bytes)),
                        )
                    self.search_status.set(f"找到 {len(books)} 条可见结果")
                elif event == "single_progress":
                    current, total, title = payload
                    if total:
                        self.search_progress.configure(maximum=total, value=min(current, total), mode="determinate")
                        self.search_status.set(f"{title}：{human_size(current)} / {human_size(total)}")
                    else:
                        self.search_progress.configure(mode="indeterminate")
                        self.search_progress.start(10)
                        self.search_status.set(f"{title}：{human_size(current)}")
                elif event == "single_done":
                    book, result = payload
                    self.search_progress.stop()
                    self.search_progress.configure(mode="determinate", value=0)
                    message = f"历史中已存在：\n{result.path}" if result.skipped else f"下载完成：\n{result.path}"
                    self.search_status.set(message.replace("\n", " "))
                    messagebox.showinfo("完成", message)
                    self._load_history()
                elif event == "batch_event":
                    batch_event, data = payload
                    self._handle_batch_event(batch_event, data)
                elif event == "worker_error":
                    label, error, details = payload
                    self.global_status.set(f"{label} 失败：{error}")
                    if label == "search":
                        self.search_status.set(f"检索失败：{error}")
                    messagebox.showerror("任务失败", str(error))
                elif event == "worker_idle":
                    self.search_button.configure(state="normal")
                    if payload != "batch":
                        self.global_status.set("就绪")
        except queue.Empty:
            pass
        self.root.after(100, self._process_messages)

    def _on_close(self) -> None:
        self.cancel_event.set()
        self.resume_event.set()
        self.global_status.set("正在关闭浏览器…")
        self.browser.close()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    BookBuilderApp(root)
    root.mainloop()
