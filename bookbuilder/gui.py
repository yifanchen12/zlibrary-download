from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import webbrowser
import math
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageOps, ImageTk

from .browser import BrowserController, BrowserError
from .config import Settings, app_data_dir, normalize_base_url
from .database import HistoryDatabase
from .models import BatchOptions, Book
from .reader import ReaderError, SUPPORTED_SUFFIXES, read_document
from .services import DownloadService, LibraryBuilder
from .source_discovery import (
    SourceDiscoveryError,
    SourceDiscoveryResult,
    discover_preferred_source,
    managed_source_origin,
    source_check_due,
)
from .utils import human_size, split_keywords


SUMERU_THEME = {
    "forest_950": "#15382F",
    "forest_900": "#1D493C",
    "forest_800": "#2B5C49",
    "forest_700": "#3E765D",
    "leaf": "#73A568",
    "leaf_hover": "#5D8E53",
    "mint": "#DCEBD3",
    "ice": "#EEF4E8",
    "pale": "#F7FAF2",
    "surface": "#FFFDF6",
    "border": "#D5DEC7",
    "gold": "#C3A85C",
    "gold_soft": "#E9DCA9",
    "text": "#26372F",
    "muted": "#6E7D73",
    "danger": "#B85B58",
    "sidebar": "#EFF4E7",
    "card": "#FCFDF8",
    "card_radius": 20,
    "button_radius": 18,
    "gap": 14,
}

# Backward-compatible semantic aliases keep the interaction code independent
# from the visual theme. Future nations can swap this one token map.
PALETTE = {
    **SUMERU_THEME,
    "navy": SUMERU_THEME["forest_950"],
    "deep_blue": SUMERU_THEME["forest_800"],
    "blue": SUMERU_THEME["leaf"],
    "blue_hover": SUMERU_THEME["leaf_hover"],
    "cyan": SUMERU_THEME["gold"],
}

TYPOGRAPHY = {
    "ui": ("Microsoft YaHei UI", 9),
    "title": ("Microsoft YaHei UI", 20, "bold"),
    "section": ("Microsoft YaHei UI", 15, "bold"),
    "small": ("Microsoft YaHei UI", 8),
    "mono": ("Consolas", 9),
}

BROWSER_MODE_LABELS = {
    "auto": "自动兼容（推荐）",
    "headless": "完全无窗口",
    "compatibility": "兼容模式（隐藏 Chrome）",
}
BROWSER_MODE_VALUES = {label: value for value, label in BROWSER_MODE_LABELS.items()}
HOME_PAGE, SEARCH_PAGE, LIBRARY_PAGE, FAVORITES_PAGE, DOWNLOADS_PAGE, READING_PAGE, SETTINGS_PAGE = range(7)


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative


def rounded(canvas: tk.Canvas, box: tuple, radius: int = 18, **options):
    x, y, right, bottom = box
    r = min(radius, max(0, (right-x)/2), max(0, (bottom-y)/2))
    points = []
    for cx, cy, start in ((x+r,y+r,180),(right-r,y+r,270),(right-r,bottom-r,0),(x+r,bottom-r,90)):
        for step in range(9):
            angle=math.radians(start+step*90/8)
            points.extend((cx+r*math.cos(angle),cy+r*math.sin(angle)))
    return canvas.create_polygon(points, **options)


class PillButton(tk.Canvas):
    """Small keyboard-operable canvas button, for rounded home-page controls."""
    def __init__(self, parent, text, command, width=110, height=38, primary=False, bg=None):
        super().__init__(parent, width=width, height=height, bg=bg or SUMERU_THEME["pale"],
                         highlightthickness=0, takefocus=1, cursor="hand2")
        self.text, self.command, self.primary = text, command, primary
        self.enabled = True; self.hover = False; self.selected = False
        self.bind("<Configure>", self.draw)
        self.bind("<Enter>", lambda _: self._hover(True))
        self.bind("<Leave>", lambda _: self._hover(False))
        self.bind("<Button-1>", lambda _: (self.focus_set(), self.invoke()))
        self.bind("<Return>", lambda _: self.invoke())
        self.bind("<space>", lambda _: self.invoke())
        self.bind("<FocusIn>", self.draw); self.bind("<FocusOut>", self.draw)

    def _hover(self, value):
        self.hover = value; self.draw()

    def invoke(self):
        if self.enabled: return self.command()

    def set_enabled(self, value):
        self.enabled = bool(value); self.configure(takefocus=int(self.enabled), cursor="hand2" if value else "arrow"); self.draw()

    def draw(self, _event=None):
        self.delete("all"); w,h=self.winfo_width(),self.winfo_height()
        active=self.primary or self.selected
        fill=("#789762" if self.hover else "#88A96F") if active else ("#E8F0DE" if self.hover else "#F8FBF3")
        foreground="white" if active else SUMERU_THEME["forest_900"]
        if not self.enabled:fill="#EDF1E7";foreground="#88927F"
        border=SUMERU_THEME["gold"] if self.focus_get()==self and self.enabled else "#D7E3CA"
        rounded(self,(1,1,w-1,h-1),SUMERU_THEME["button_radius"],fill=fill,outline=border,width=1)
        self.create_text(w/2,h/2,text=self.text,fill=foreground,font=("Microsoft YaHei UI",10,"bold" if active else "normal"))


class Card(tk.Canvas):
    def __init__(self, parent, height, bg=None):
        super().__init__(parent, width=1, height=height, bg=bg or SUMERU_THEME["pale"],highlightthickness=0)
        self.minimum_height=height
        self.body=tk.Frame(self,bg=SUMERU_THEME["card"])
        self.body.bind("<Configure>",lambda _:self.configure(height=max(self.minimum_height,self.body.winfo_reqheight()+29)))
        self.window=self.create_window(14,13,window=self.body,anchor="nw")
        self.bind("<Configure>",self.draw)

    def draw(self,_event=None):
        w,h=self.winfo_width(),self.winfo_height()
        self.delete("border")
        rounded(self,(2,4,w-2,h-1),20,fill="#E6EDDE",outline="",tags="border")
        rounded(self,(1,1,w-3,h-4),20,fill=SUMERU_THEME["card"],outline="#DFE7D6",tags="border")
        self.tag_lower("border")
        self.itemconfigure(self.window,width=max(1,w-30))


class ScrollPage(ttk.Frame):
    def __init__(self,parent,min_width=0):
        super().__init__(parent,style="Page.TFrame")
        self.min_width=min_width
        self.canvas=tk.Canvas(self,bg=SUMERU_THEME["pale"],highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        self.vertical=ttk.Scrollbar(self,command=self.canvas.yview)
        self.vertical.grid(row=0,column=1,sticky="ns")
        self.horizontal=ttk.Scrollbar(self,orient="horizontal",command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vertical.set,xscrollcommand=self.horizontal.set)
        self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
        self.body=ttk.Frame(self.canvas,style="Page.TFrame",padding=(4,4))
        self.window=self.canvas.create_window(0,0,window=self.body,anchor="nw")
        self.pending=None
        self.canvas.bind("<Configure>",self.schedule)
        self.body.bind("<Configure>",self.schedule)

    def schedule(self,_event=None):
        if self.pending is None:self.pending=self.after_idle(self.sync)

    def sync(self):
        self.pending=None
        width=max(self.min_width,self.canvas.winfo_width())
        height=max(self.canvas.winfo_height(),self.body.winfo_reqheight())
        self.canvas.itemconfigure(self.window,width=width)
        self.canvas.configure(scrollregion=(0,0,width,height))
        if self.min_width>self.canvas.winfo_width():self.horizontal.grid(row=1,column=0,sticky="ew")
        else:self.horizontal.grid_remove()


class ReaderWindow:
    def __init__(self, parent: tk.Misc, database: HistoryDatabase, row, on_saved) -> None:
        self.database = database
        self.download_id = int(row["id"])
        self.on_saved = on_saved
        self.position = 0.0
        path = Path(row["local_path"] or "")
        content = read_document(path)
        state = database.reading_state(self.download_id)
        start = float(state["progress"] or 0) if state else 0.0
        database.record_reading(self.download_id)

        self.window = tk.Toplevel(parent)
        self.window.title(f"阅读 · {row['title']}")
        self.window.geometry("920x720")
        self.window.minsize(620, 480)
        self.window.configure(background=SUMERU_THEME["pale"])
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        header = tk.Frame(self.window, bg=SUMERU_THEME["forest_900"])
        header.pack(fill="x")
        tk.Label(
            header,
            text=row["title"],
            bg=SUMERU_THEME["forest_900"],
            fg="white",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(side="left", padx=18, pady=12)
        self.status = tk.StringVar(value="阅读位置 0%")
        tk.Label(
            header,
            textvariable=self.status,
            bg=SUMERU_THEME["forest_900"],
            fg=SUMERU_THEME["gold_soft"],
            font=TYPOGRAPHY["ui"],
        ).pack(side="right", padx=18)
        frame = tk.Frame(self.window, bg=SUMERU_THEME["pale"])
        frame.pack(fill="both", expand=True, padx=18, pady=16)
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        self.text = tk.Text(
            frame,
            wrap="word",
            relief="flat",
            background="#FFFDF6",
            foreground=SUMERU_THEME["text"],
            selectbackground=SUMERU_THEME["mint"],
            padx=36,
            pady=28,
            spacing1=4,
            spacing3=8,
            font=("Microsoft YaHei UI", 12),
        )
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", content)
        self.text.configure(state="disabled", yscrollcommand=lambda first, last: self._scroll(scrollbar, first, last))
        scrollbar.configure(command=self.text.yview)
        self.window.after_idle(lambda: self._restore(start))

    def _restore(self, position: float) -> None:
        first, last = map(float, self.text.yview())
        self.text.yview_moveto(position * max(0.0, 1.0 - (last - first)))

    def _scroll(self, scrollbar: ttk.Scrollbar, first: str, last: str) -> None:
        scrollbar.set(first, last)
        first_value, last_value = float(first), float(last)
        available = max(0.0001, 1.0 - (last_value - first_value))
        self.position = min(1.0, max(0.0, first_value / available))
        self.status.set(f"阅读位置 {round(self.position * 100)}%")

    def close(self) -> None:
        self.database.record_reading(self.download_id, self.position)
        self.window.destroy()
        self.on_saved()


def prepare_tk_runtime(cache: Path | None = None) -> None:
    """Support this Python distribution's bundled Tcl/Tk ZIPs; no downloads."""
    try:
        tk.Tcl()
        return
    except tk.TclError:
        if getattr(sys,"frozen",False):raise
    cache=cache or (app_data_dir()/"runtime")
    for prefix,library,variable in (("libtcl","tcl_library","TCL_LIBRARY"),("libtk","tk_library","TK_LIBRARY")):
        archives=list((Path(sys.base_prefix)/"tcl").glob(prefix+"*.zip"))
        if len(archives)!=1:raise RuntimeError("Python Tcl/Tk 运行库不完整，请修复 Python 安装。")
        destination=(cache/archives[0].stem).resolve();destination.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archives[0]) as archive:
            if any(not (destination/item.filename).resolve().is_relative_to(destination) for item in archive.infolist()):
                raise RuntimeError("Invalid Tcl/Tk library archive path")
            archive.extractall(destination)
        os.environ[variable]=str(destination/library)


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
        self.source_check_active = False
        self.search_query = tk.StringVar()
        self.home_task = {"kind": "none", "state": "idle", "title": "暂无下载任务", "current": 0, "total": 0}
        self.home_rows = []
        self.shelf_mode = "history"
        self._image_cache = {}

        self.root.title("ZLibrary 智慧书库 · 须弥主题")
        self.root.geometry(f"{min(1600,self.root.winfo_screenwidth()-60)}x{min(940,self.root.winfo_screenheight()-90)}")
        self.root.minsize(1100, 760)
        self.root.configure(background=PALETTE["ice"])
        self.app_icon = tk.PhotoImage(file=str(resource_path("assets/app_icon.png")))
        self.root.iconphoto(True, self.app_icon)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_style()
        self._build_ui()
        self._load_history()
        self.root.after(100, self._process_messages)
        self.root.after(600, self._start_source_check)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        font = TYPOGRAPHY["ui"]
        style.configure(".", font=font, background=PALETTE["surface"], foreground=PALETTE["text"])
        style.configure("TFrame", background=PALETTE["surface"])
        style.configure("App.TFrame", background=PALETTE["ice"])
        style.configure("Page.TFrame", background=PALETTE["pale"])
        style.configure("Card.TFrame", background=PALETTE["surface"], relief="flat")
        style.configure("Hero.TFrame", background="#E8F1DE")
        style.configure("TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
        style.configure("Page.TLabel", background=PALETTE["pale"], foreground=PALETTE["text"])
        style.configure("Hero.TLabel", background="#E8F1DE", foreground=PALETTE["forest_900"])
        style.configure("HeroHint.TLabel", background="#E8F1DE", foreground=PALETTE["forest_700"])
        style.configure("Title.TLabel", background=PALETTE["pale"], foreground=PALETTE["forest_900"], font=TYPOGRAPHY["section"])
        style.configure("Eyebrow.TLabel", background=PALETTE["pale"], foreground=PALETTE["gold"], font=("Consolas", 8, "bold"))
        style.configure("Hint.TLabel", foreground=PALETTE["muted"], font=TYPOGRAPHY["ui"])
        style.configure("PageHint.TLabel", background=PALETTE["pale"], foreground=PALETTE["muted"], font=TYPOGRAPHY["ui"])
        style.configure("Metric.TLabel", background=PALETTE["surface"], foreground=PALETTE["forest_900"], font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("MetricHint.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"], font=TYPOGRAPHY["small"])
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
            foreground=PALETTE["forest_800"],
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(4, 0),
        )
        style.layout("Page.TNotebook.Tab", [])
        style.configure(
            "Page.TNotebook",
            background=PALETTE["ice"],
            borderwidth=0,
            tabmargins=0,
        )
        style.configure(
            "TButton",
            background="#EDF4E7",
            foreground=PALETTE["forest_800"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            borderwidth=1,
            padding=(13, 7),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", "#DFEBD7"), ("pressed", "#D0E2C5"), ("disabled", "#F0F2ED")],
            foreground=[("disabled", "#A0AAA3")],
        )
        style.configure(
            "Accent.TButton",
            background=PALETTE["forest_700"],
            foreground="#FFFFFF",
            bordercolor=PALETTE["forest_700"],
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(16, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("active", PALETTE["leaf_hover"]), ("pressed", PALETTE["forest_800"]), ("disabled", "#AABCA8")],
            foreground=[("disabled", "#F4F7F1")],
        )
        style.configure(
            "Gold.TButton",
            background=PALETTE["gold_soft"],
            foreground=PALETTE["forest_950"],
            bordercolor=PALETTE["gold"],
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(16, 8),
        )
        style.map("Gold.TButton", background=[("active", "#E1CF8E"), ("pressed", "#D4BC6D")])
        style.configure(
            "Danger.TButton",
            background="#FBEAE5",
            foreground=PALETTE["danger"],
            bordercolor="#ECC6BE",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#F5DAD3"), ("pressed", "#EDC8BF")])
        style.configure(
            "TEntry",
            fieldbackground=PALETTE["pale"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            insertcolor=PALETTE["forest_700"],
            padding=(8, 7),
        )
        style.map("TEntry", bordercolor=[("focus", PALETTE["leaf"])], lightcolor=[("focus", PALETTE["leaf"])])
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
        style.map("Treeview", background=[("selected", "#D7E8CF")], foreground=[("selected", PALETTE["forest_950"])])
        style.configure(
            "Treeview.Heading",
            font=("Microsoft YaHei UI", 9, "bold"),
            background="#E7F0E0",
            foreground=PALETTE["forest_800"],
            bordercolor=PALETTE["border"],
            padding=(6, 7),
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#D9E8D1")])
        style.configure(
            "Horizontal.TProgressbar",
            background=PALETTE["leaf"],
            troughcolor="#DDE8D4",
            bordercolor="#DDE8D4",
            lightcolor=PALETTE["gold_soft"],
            darkcolor=PALETTE["forest_700"],
            thickness=10,
        )
        style.configure(
            "Status.TLabel",
            background=PALETTE["pale"],
            foreground=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
            padding=(12, 6),
        )
        style.configure("TCheckbutton", background=PALETTE["surface"], foreground=PALETTE["text"], padding=3)

    def _scene(self, role, width, height, fade=0.0, radius=0):
        key=(width,height,fade,radius)
        cached=self._image_cache.get(role)
        if cached and cached[0]==key:return cached[1]
        image=ImageOps.fit(self.palace_source,(max(1,width),max(1,height)),method=Image.Resampling.LANCZOS)
        if fade:image=Image.blend(image,Image.new("RGB",image.size,"#F6FAEF"),fade)
        if radius:
            image=image.convert("RGBA");mask=Image.new("L",image.size,0)
            ImageDraw.Draw(mask).rounded_rectangle((0,0,width-1,height-1),radius=radius,fill=255)
            image.putalpha(mask)
        photo=ImageTk.PhotoImage(image)
        self._image_cache[role]=(key,photo)
        return photo

    def _draw_header(self, event=None):
        canvas=self.header;w=canvas.winfo_width();h=canvas.winfo_height()
        if w<600:return
        canvas.delete("all")
        canvas.create_image(0,0,image=self._scene("header",w,h,.69,20),anchor="nw")
        form_width=w-276
        canvas.create_text(25+form_width/2,39,text="知识是永不凋零的森林\n而你，正是点亮它的光",justify="center",
                           fill=PALETTE["forest_900"],font=("KaiTi",16),width=form_width)
        canvas.create_text(40,38,text="❧",fill=PALETTE["leaf"],font=("Georgia",30))
        rounded(canvas,(24,85,24+form_width,143),28,fill="#FFFFFF",outline="#8CAA70",width=1.3)
        canvas.create_window(40,95,window=self.header_form,anchor="nw",width=form_width-140,height=36)
        canvas.create_window(form_width-87,93,window=self.header_search,anchor="nw",width=105,height=42)
        canvas.create_text(25,169,text="快捷检索：",anchor="w",fill=PALETTE["muted"],font=TYPOGRAPHY["ui"])
        x=97
        for button in self.quick_buttons:
            width=76 if len(button.text)>3 else 62
            if x+width>form_width+24:break
            canvas.create_window(x,153,window=button,anchor="nw",width=width,height=32)
            x+=width+7
        canvas.create_image(w-120,110,image=self.guide_image)
        canvas.create_text(w-252,45,text="小小的书页里，\n也有大大的世界。",anchor="e",justify="center",
                           fill="#657D50",font=("KaiTi",11))
        canvas.create_line(25,h-3,w-25,h-3,fill="#E0E8D3")

    def _header_search(self, query=None):
        if query is not None:self.search_query.set(query)
        self._show_page(SEARCH_PAGE)
        self._start_search()

    def _header_hint(self,*_args):
        if self.search_query.get() or self.root.focus_get()==self.header_entry:
            self.header_placeholder.place_forget()
        else:self.header_placeholder.place(x=35,y=8)

    def _build_ui(self):
        with Image.open(resource_path("assets/sumeru_palace.png")) as source:self.palace_source=source.convert("RGB")
        with Image.open(resource_path("assets/nahida_header.png")) as source:self.guide_source=source.convert("RGBA")
        guide=self.guide_source.copy();guide.thumbnail((216,216),Image.Resampling.LANCZOS)
        self.guide_image=ImageTk.PhotoImage(guide)
        avatar=self.guide_source.copy();avatar.thumbnail((42,42),Image.Resampling.LANCZOS)
        self.avatar=ImageTk.PhotoImage(avatar)
        shell=tk.Frame(self.root,bg=PALETTE["pale"],highlightthickness=1,highlightbackground="#BECFA8")
        shell.pack(fill="both",expand=True,padx=12,pady=12)
        self.sidebar=tk.Frame(shell,width=206,bg=PALETTE["sidebar"])
        self.sidebar.pack(side="left",fill="y");self.sidebar.pack_propagate(False)
        self.sidebar_canvas=tk.Canvas(self.sidebar,highlightthickness=0,bg=PALETTE["sidebar"])
        self.sidebar_canvas.place(x=0,y=0,relwidth=1,relheight=1)
        self.sidebar_canvas.bind("<Configure>",self._draw_sidebar_backdrop)
        content=ttk.Frame(shell,style="Page.TFrame");content.pack(side="right",fill="both",expand=True)
        self.header=tk.Canvas(content,height=206,highlightthickness=0,bg=PALETTE["pale"])
        self.header.pack(fill="x",padx=12,pady=(6,0))
        self.header_form=tk.Frame(self.header,bg="white")
        tk.Label(self.header_form,text="⌕",font=("Segoe UI Symbol",23),bg="white",fg=PALETTE["forest_800"]).pack(side="left",padx=(0,8))
        self.header_entry=tk.Entry(self.header_form,textvariable=self.search_query,bg="white",fg=PALETTE["text"],
                                   insertbackground=PALETTE["forest_800"],relief="flat",font=("Microsoft YaHei UI",11))
        self.header_entry.pack(side="left",fill="both",expand=True,pady=5)
        self.header_entry.bind("<Return>",lambda _:self._header_search())
        self.header_entry.bind("<FocusIn>",self._header_hint);self.header_entry.bind("<FocusOut>",self._header_hint)
        self.header_placeholder=tk.Label(self.header_form,text="搜索书名或 ISBN…",bg="white",fg="#929A90",font=("Microsoft YaHei UI",10))
        self.header_placeholder.bind("<Button-1>",lambda _:self.header_entry.focus_set())
        self.search_query.trace_add("write",self._header_hint);self._header_hint()
        self.header_search=PillButton(self.header,"搜索",self._header_search,primary=True,bg="white")
        self.quick_buttons=[PillButton(self.header,q,lambda term=q:self._header_search(term),height=32) for q in ("原神","小说","人工智能","心理学","历史","编程","艺术")]
        self.header.bind("<Configure>",self._draw_header)
        self.global_status=tk.StringVar(value="让知识，如森林般生长。  ·  检索与下载在后台执行")
        ttk.Label(content,textvariable=self.global_status,anchor="w",style="Status.TLabel",wraplength=1050).pack(fill="x",side="bottom",padx=18,pady=(0,5))
        self.notebook=ttk.Notebook(content,style="Page.TNotebook")
        self.notebook.pack(fill="both",expand=True,padx=12,pady=(7,4))
        self.page_views=[ScrollPage(self.notebook,0 if i==0 else 950) for i in range(7)]
        (
            self.home_tab,
            self.search_tab,
            self.batch_tab,
            self.favorites_tab,
            self.history_tab,
            self.reading_tab,
            self.settings_tab,
        )=[page.body for page in self.page_views]
        for page,title in zip(
            self.page_views,
            ("首页","检索下载","模糊建库","收藏","下载历史","阅读记录","设置与授权"),
            strict=True,
        ):
            self.notebook.add(page,text=title)
        self._build_home_tab();self._build_search_tab();self._build_batch_tab();self._build_favorites_tab()
        self._build_history_tab();self._build_reading_tab();self._build_settings_tab()
        self._build_sidebar();self.notebook.bind("<<NotebookTabChanged>>",self._sync_sidebar_selection)
        self.root.bind("<MouseWheel>",self._page_wheel,add="+")
        self._show_page(HOME_PAGE)

    def _page_wheel(self,event):
        widget=event.widget
        if isinstance(widget,(ttk.Treeview,tk.Text,ttk.Combobox)):return
        while widget is not None:
            if isinstance(widget,ScrollPage):
                if widget.body.winfo_reqheight()>widget.canvas.winfo_height():
                    widget.canvas.yview_scroll(-int(event.delta/120) or (-1 if event.delta>0 else 1),"units")
                return
            widget=getattr(widget,"master",None)

    def _draw_sidebar_backdrop(self,_event=None):
        c=self.sidebar_canvas;w,h=c.winfo_width(),c.winfo_height()
        if w<10 or h<10:return
        c.delete("all")
        c.create_image(0,0,image=self._scene("sidebar",w,h,.74),anchor="nw")
        c.create_line(w-1,10,w-1,h-10,fill="#D4DFC6")
        c.create_text(w/2,71,text="ZLibrary",fill=PALETTE["forest_900"],font=("Georgia",27,"italic"))
        c.create_text(w/2,107,text="—  智慧书库  —",fill="#6D8459",font=("Microsoft YaHei UI",11))
        c.create_text(w/2,156,text="让知识，\n如繁林般生长",fill="#7E8F69",font=("KaiTi",14),justify="center")
        c.create_text(26,29,text="❧",fill=PALETTE["leaf"],font=("Georgia",20))
        if h>800:
            c.create_line(35,h-218,w/2,h-254,w-35,h-218,fill="#BEBC86",width=1.2)
            c.create_arc(37,h-257,w-37,h-112,start=0,extent=180,style="arc",outline="#BEBC86",width=1.2)
            c.create_text(w/2,h-170,text="在书页之间\n见更大的世界",fill="#6B8352",font=("KaiTi",14),justify="center")
        rounded(c,(9,h-70,w-9,h-9),18,fill="#F8FBF1",outline="#D9E2CD")
        c.create_image(35,h-39,image=self.avatar)
        c.create_text(63,h-49,text="森林的旅人",anchor="w",fill="#49683D",font=("Microsoft YaHei UI",10))
        c.create_text(63,h-28,text="本地智慧书库",anchor="w",fill="#8B997A",font=("Microsoft YaHei UI",8))

    def _build_sidebar(self):
        nav=tk.Frame(self.sidebar,bg=PALETTE["sidebar"]);nav.place(x=12,y=204,width=182)
        self.nav_buttons=[]
        for symbol,label,index in (("⌂","首页",HOME_PAGE),("⌕","搜索",SEARCH_PAGE),("▤","书库",LIBRARY_PAGE),
                                   ("☆","收藏",FAVORITES_PAGE),("↓","下载",DOWNLOADS_PAGE),
                                   ("◷","阅读记录",READING_PAGE),("⚙","设置",SETTINGS_PAGE)):
            button=PillButton(nav,f"{symbol}   {label}",lambda page=index:self._show_page(page),height=44,bg=PALETTE["sidebar"])
            button.pack(fill="x",pady=3)
            button.page=index
            self.nav_buttons.append(button)

    def _show_page(self,index):
        self.notebook.select(index);self._sync_sidebar_selection()
        if index==HOME_PAGE:self._refresh_home()
        elif index==FAVORITES_PAGE:self._load_favorites()
        elif index==READING_PAGE:self._load_reading_history()

    def _sync_sidebar_selection(self,_event=None):
        if not hasattr(self,"nav_buttons"):return
        current=self.notebook.index(self.notebook.select())
        for button in self.nav_buttons:
            button.selected=button.page==current;button.draw()


    @staticmethod
    def _section_intro(parent: ttk.Frame, eyebrow: str, title: str, subtitle: str) -> None:
        intro = ttk.Frame(parent, style="Page.TFrame")
        intro.pack(fill="x", pady=(0, 12))
        ttk.Label(intro, text=eyebrow, style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(intro, text=title, style="Title.TLabel").pack(anchor="w", pady=(2, 1))
        ttk.Label(intro, text=subtitle, style="PageHint.TLabel").pack(anchor="w")

    def _home_label(self,parent,text="",size=10,color=None,**kwargs):
        return tk.Label(parent,text=text,bg=PALETTE["card"],fg=color or PALETTE["text"],font=("Microsoft YaHei UI",size),
                        anchor=kwargs.pop("anchor","w"),**kwargs)

    def _build_home_tab(self):
        self.home_tab.configure(padding=(0,0))
        self.home_layout=tk.Frame(self.home_tab,bg=PALETTE["pale"])
        self.home_layout.pack(fill="x",anchor="n")
        self.home_layout.columnconfigure(0,weight=1)
        self.home_left=tk.Frame(self.home_layout,bg=PALETTE["pale"])
        self.home_right=tk.Frame(self.home_layout,bg=PALETTE["pale"])
        self.home_left.grid(row=0,column=0,sticky="nsew",padx=(0,12))
        self.home_right.grid(row=0,column=1,sticky="new")
        self.home_hero=tk.Canvas(self.home_left,height=244,bg=PALETTE["pale"],highlightthickness=0)
        self.home_hero.pack(fill="x")
        self.hero_button=PillButton(self.home_hero,"开启阅读之旅  →",lambda:self._show_page(SEARCH_PAGE),width=154,primary=True)
        self.home_hero.bind("<Configure>",self._draw_home_hero)
        self.categories=tk.Frame(self.home_left,bg=PALETTE["pale"])
        self.categories.pack(fill="x",pady=12)
        self.category_buttons=[]
        topics=(("▤","小说","故事与远方","小说","文学, 小说", "#5E9B60"),
                ("♜","人文社科","思想与文明","人文社会科学","历史, 哲学, 社会","#BE8D45"),
                ("▣","计算机","技术与未来","计算机科学","编程, 算法, 系统","#4C93AF"),
                ("▥","经济管理","商业与社会","经济管理","经济, 管理, 金融","#BF855F"),
                ("♧","生活艺术","发现生活之美","生活艺术","艺术, 生活, 设计","#B2837D"),
                ("❧","自然科学","探索世界奥秘","自然科学","科普, 基础, 教材","#599360"))
        for index,(icon,title,subtitle,query,extras,color) in enumerate(topics):
            self.categories.columnconfigure(index,weight=1,uniform="topic")
            button=tk.Canvas(self.categories,width=1,height=72,bg=PALETTE["pale"],highlightthickness=0,takefocus=1,cursor="hand2")
            button.grid(row=0,column=index,sticky="ew",padx=(0 if index==0 else 4,0 if index==5 else 4))
            def draw(_event=None,c=button,symbol=icon,label=title,note=subtitle,tint=color):
                c.delete("all");w=c.winfo_width()
                rounded(c,(1,2,w-1,69),15,fill=PALETTE["card"],outline=PALETTE["gold"] if c.focus_get()==c else "#DEE6D5")
                c.create_text(21,30,text=symbol,fill=tint,font=("Segoe UI Symbol",21))
                c.create_text(42,25,text=label,anchor="w",fill=PALETTE["text"],font=("Microsoft YaHei UI",9,"bold"))
                if w>125:c.create_text(42,46,text=note,anchor="w",fill=PALETTE["muted"],font=("Microsoft YaHei UI",8))
            action=lambda _event=None,q=query,e=extras:self._prepare_topic(q,e)
            button.bind("<Configure>",draw);button.bind("<FocusIn>",draw);button.bind("<FocusOut>",draw)
            button.bind("<Button-1>",action);button.bind("<Return>",action);button.bind("<space>",action)
            self.category_buttons.append(button)

        self.shelf_card=Card(self.home_left,294);self.shelf_card.pack(fill="x")
        shelf_head=tk.Frame(self.shelf_card.body,bg=PALETTE["card"]);shelf_head.pack(fill="x")
        self.shelf_title=self._home_label(shelf_head,"❧  新近入库",13);self.shelf_title.pack(side="left")
        self.shelf_all=PillButton(shelf_head,"查看全部 ›",lambda:self._show_page(DOWNLOADS_PAGE if self.shelf_mode=="history" else SEARCH_PAGE),width=84,height=29,bg=PALETTE["card"])
        self.shelf_all.pack(side="right")
        self.shelf_toggle=PillButton(shelf_head,"看检索结果",self._toggle_shelf,width=92,height=29,bg=PALETTE["card"])
        self.shelf_toggle.pack(side="right",padx=5)
        self.shelf_canvas=tk.Canvas(self.shelf_card.body,height=220,bg=PALETTE["card"],highlightthickness=0,takefocus=1)
        self.shelf_canvas.pack(fill="both",expand=True,pady=(7,0));self.shelf_canvas.bind("<Configure>",self._draw_shelf)
        self.shelf_index=0;self.shelf_items=[]
        self.shelf_canvas.bind("<FocusIn>",self._draw_shelf);self.shelf_canvas.bind("<FocusOut>",self._draw_shelf)
        self.shelf_canvas.bind("<Left>",lambda _:self._shelf_key(-1));self.shelf_canvas.bind("<Right>",lambda _:self._shelf_key(1))
        self.shelf_canvas.bind("<Return>",lambda _:self._open_shelf_item(self.shelf_index))

        self.read_card=Card(self.home_right,185)
        self._home_label(self.read_card.body,"❧  我的阅读",13).pack(anchor="w")
        reading=tk.Frame(self.read_card.body,bg=PALETTE["card"]);reading.pack(fill="x",pady=(11,5))
        self.read_cover=tk.Canvas(reading,width=54,height=76,bg=PALETTE["card"],highlightthickness=0)
        self.read_cover.pack(side="left",padx=(0,10))
        info=tk.Frame(reading,bg=PALETTE["card"]);info.pack(side="left",fill="both",expand=True)
        self.read_title=self._home_label(info,"还没有入库的书",11,wraplength=180);self.read_title.pack(anchor="w")
        self.read_detail=self._home_label(info,"阅读进度尚未接入",9,color=PALETTE["muted"]);self.read_detail.pack(anchor="w",pady=(5,5))
        self.read_button=PillButton(info,"打开最近文件",self._open_recent_file,width=160,height=32,primary=True,bg=PALETTE["card"])
        self.read_button.pack(fill="x")
        self._home_label(self.read_card.body,"EPUB / 文本内置阅读；其他格式系统打开",8,color=PALETTE["muted"]).pack(anchor="w",pady=(5,0))

        self.task_card=Card(self.home_right,240)
        taskhead=tk.Frame(self.task_card.body,bg=PALETTE["card"]);taskhead.pack(fill="x")
        self._home_label(taskhead,"❧  下载任务",13).pack(side="left")
        PillButton(taskhead,"查看 ›",lambda:self._show_page(LIBRARY_PAGE if self.home_task["kind"]=="batch" else SEARCH_PAGE),width=64,height=27,bg=PALETTE["card"]).pack(side="right")
        self.task_title=self._home_label(self.task_card.body,"暂无下载任务",11,wraplength=230);self.task_title.pack(anchor="w",pady=(13,4))
        self.task_detail=self._home_label(self.task_card.body,"从搜索开始，收集下一本好书",9,color=PALETTE["muted"],wraplength=230)
        self.task_detail.pack(anchor="w")
        self.home_task_bar=ttk.Progressbar(self.task_card.body,mode="determinate",maximum=100)
        self.home_task_bar.pack(fill="x",pady=(12,10))
        controls=tk.Frame(self.task_card.body,bg=PALETTE["card"]);controls.pack(fill="x")
        self.home_pause=PillButton(controls,"暂停",self._toggle_pause,width=110,height=32,bg=PALETTE["card"])
        self.home_pause.pack(side="left")
        self.home_stop=PillButton(controls,"停止",self._stop_batch,width=110,height=32,bg=PALETTE["card"])
        self.home_stop.pack(side="right")
        self.task_hint=self._home_label(self.task_card.body,"批量任务在安全检查点暂停或停止",8,color=PALETTE["muted"],wraplength=230)
        self.task_hint.pack(anchor="w",pady=(8,0))

        self.discover_card=Card(self.home_right,195)
        self._home_label(self.discover_card.body,"❧  为你发现",13).pack(anchor="w")
        for title,query in (("探索人工智能  ↗","人工智能"),("翻开自然科学  ↗","自然科学"),("漫游人文历史  ↗","历史")):
            PillButton(self.discover_card.body,title,lambda q=query:self._header_search(q),height=31,bg=PALETTE["card"]).pack(fill="x",pady=(6,0))
        self._home_label(self.discover_card.body,"主题检索入口 · 非个性化推荐",8,color=PALETTE["muted"]).pack(anchor="w",pady=(7,0))
        self._compact_home=None
        self.home_layout.bind("<Configure>",self._arrange_home)
        self._update_home_task()

    def _arrange_home(self,event=None):
        compact=self.home_layout.winfo_width()<1110
        if compact==self._compact_home:return
        self._compact_home=compact
        cards=(self.read_card,self.task_card,self.discover_card)
        for card in cards:card.grid_forget()
        if compact:
            self.home_layout.columnconfigure(1,minsize=0,weight=0)
            self.home_left.grid_configure(padx=0)
            self.home_right.grid(row=1,column=0,sticky="ew",pady=(12,0))
            for i,card in enumerate(cards):
                self.home_right.columnconfigure(i,weight=1,uniform="sidecard")
                card.grid(row=0,column=i,sticky="nsew",padx=(0 if i==0 else 4,0 if i==2 else 4))
        else:
            self.home_layout.columnconfigure(1,minsize=302,weight=0)
            self.home_left.grid_configure(padx=(0,12))
            self.home_right.grid(row=0,column=1,sticky="new",pady=0)
            for i in range(3):self.home_right.columnconfigure(i,weight=0,uniform="")
            self.home_right.columnconfigure(0,weight=1)
            for i,card in enumerate(cards):card.grid(row=i,column=0,sticky="ew",pady=(0,10 if i<2 else 0))

    def _draw_home_hero(self,_event=None):
        c=self.home_hero;w,h=c.winfo_width(),c.winfo_height()
        if w<10:return
        c.delete("all");c.create_image(0,0,image=self._scene("hero",w,h,0.05,19),anchor="nw")
        center=w*.51
        c.create_text(center,40,text="❧  阅 读  ❧",fill="#365C2D",font=("KaiTi",26))
        c.create_text(center,109,text="让平凡的日子\n也有星光",justify="center",fill="#2F5429",font=("KaiTi",25))
        c.create_text(center,174,text="在书籍中，遇见更广阔的自己",fill="#65804D",font=("KaiTi",12))
        c.create_text(23,h-22,text="A BRIGHTER YOU\nTHROUGH READING",anchor="w",fill="#F5F7E6",font=("Georgia",8))
        c.create_window(w-172,h-48,window=self.hero_button,anchor="nw",width=154,height=37)

    def _prepare_topic(self, query, extras):
        self.batch_query.set(query);self.batch_extra.set(extras);self._show_page(LIBRARY_PAGE)

    def _toggle_shelf(self):
        self.shelf_mode="search" if self.shelf_mode=="history" else "history"
        self._refresh_home()

    def _refresh_home(self):
        if not hasattr(self,"shelf_canvas"):return
        self.home_rows=[dict(row) for row in self.database.recent()]
        completed=[row for row in self.home_rows if row["status"]=="completed"]
        if self.shelf_mode=="history":
            self.shelf_items=[{"title":row["title"],"author":row["author"] or "作者未提供","format":row["file_format"] or "BOOK","row":row} for row in completed[:6]]
        else:
            self.shelf_items=[{"title":book.title,"author":book.author or "作者未提供","format":book.file_format or "BOOK","iid":iid} for iid,book in list(self.search_results.items())[:6]]
        self.shelf_title.configure(text="❧  新近入库" if self.shelf_mode=="history" else "❧  检索结果")
        self.shelf_toggle.text="看检索结果" if self.shelf_mode=="history" else "看最近入库";self.shelf_toggle.draw()
        self.shelf_index=0;self._draw_shelf()
        self.recent_file=completed[0] if completed else None
        title=self.recent_file["title"] if self.recent_file else "还没有入库的书"
        self.read_title.configure(text=title[:28]+("…" if len(title)>28 else ""))
        self.read_button.set_enabled(self.recent_file is not None)
        state=self.database.reading_state(int(self.recent_file["id"])) if self.recent_file else None
        if state:
            suffix=Path(self.recent_file["local_path"] or "").suffix.lower()
            detail=f"阅读位置 {round(float(state['progress'])*100)}%" if suffix in SUPPORTED_SUFFIXES else f"已打开 {state['open_count']} 次"
        else:
            detail="尚未开始阅读"
        self.read_detail.configure(text=detail)
        self.read_cover.delete("all")
        rounded(self.read_cover,(2,2,50,74),5,fill="#87A574",outline="#678950")
        self.read_cover.create_line(8,4,8,71,fill="#C8D8B9")
        self.read_cover.create_text(29,34,text=(self.recent_file["file_format"] if self.recent_file else "BOOK") or "BOOK",fill="#F8FBF1",font=("Georgia",9))
        self.read_cover.create_text(29,56,text="❧",fill="#E0EACE",font=("Georgia",15))

    def _draw_shelf(self,_event=None):
        if not hasattr(self,"shelf_canvas"):return
        c=self.shelf_canvas;w,h=c.winfo_width(),c.winfo_height();c.delete("all")
        if w<20:return
        if not self.shelf_items:
            c.create_text(w/2,64,text="❧",fill="#A4B98E",font=("Georgia",35))
            text="书架还没有书，先去搜索一本吧" if self.shelf_mode=="history" else "还没有检索结果"
            c.create_text(w/2,111,text=text,fill="#627A51",font=("Microsoft YaHei UI",13))
            c.create_text(w/2,143,text="这里只展示真实记录；无封面时使用书名封面。",fill=PALETTE["muted"],font=("Microsoft YaHei UI",9))
            return
        count=min(6,len(self.shelf_items));gap=12;slot=(w-gap*5)/6
        colors=(("#E7EADB","#456143"),("#2C504A","#F6E8BB"),("#EDE3CB","#785B3C"),("#E4E8DE","#354A40"),("#456C85","#F2F8F7"),("#E8DAC2","#735734"))
        for index,item in enumerate(self.shelf_items[:count]):
            x=index*(slot+gap);tag=f"shelf-{index}";cover_width=max(55,slot-13);cover_height=145
            rounded(c,(x,1,x+slot,h-8),12,fill="#F6F9F0",outline=PALETTE["gold"] if index==self.shelf_index and c.focus_get()==c else "#E7EDDF",tags=tag)
            background,foreground=colors[index]
            rounded(c,(x+5,5,x+5+cover_width,5+cover_height),5,fill=background,outline="#D7DECD",tags=tag)
            c.create_line(x+12,8,x+12,146,fill=foreground,tags=tag)
            c.create_text(x+cover_width/2+7,26,text="智慧书库",fill=foreground,font=("KaiTi",9),tags=tag)
            title=item["title"]
            c.create_text(x+cover_width/2+7,78,text=title[:22]+("…" if len(title)>22 else ""),width=cover_width-21,
                          fill=foreground,font=("KaiTi",15),justify="center",tags=tag)
            c.create_text(x+cover_width/2+7,132,text=item["format"][:10],fill=foreground,font=("Georgia",8),tags=tag)
            c.create_text(x+5,161,text=title[:10]+("…" if len(title)>10 else ""),anchor="nw",fill=PALETTE["text"],font=("Microsoft YaHei UI",9),tags=tag)
            c.create_text(x+5,181,text=item["author"][:11],anchor="nw",fill=PALETTE["muted"],font=("Microsoft YaHei UI",8),tags=tag)
            c.create_text(x+5,202,text="文字封面  ·  查看 ›",anchor="nw",fill="#839576",font=("Microsoft YaHei UI",8),tags=tag)
            c.tag_bind(tag,"<Button-1>",lambda _,i=index:self._open_shelf_item(i))
        c.configure(cursor="hand2")

    def _shelf_key(self,direction):
        if self.shelf_items:self.shelf_index=(self.shelf_index+direction)%len(self.shelf_items);self._draw_shelf()

    def _open_shelf_item(self,index):
        if index>=len(self.shelf_items):return
        item=self.shelf_items[index]
        if "row" in item:
            self._show_page(DOWNLOADS_PAGE);iid=str(item["row"]["id"]);tree=self.history_tree
        else:
            self._show_page(SEARCH_PAGE);iid=item["iid"];tree=self.search_tree
        if tree.exists(iid):tree.selection_set(iid);tree.focus(iid);tree.see(iid)

    def _open_recent_file(self):
        if not self.recent_file:return
        self._open_download(self.recent_file)

    def _set_home_task(self,**values):
        self.home_task.update(values);self._update_home_task()

    def _update_home_task(self):
        if not hasattr(self,"task_title"):return
        task=self.home_task;state=task["state"];current=int(task["current"]);total=int(task["total"])
        active=state in {"active","paused","stopping"}
        self.task_title.configure(text=task["title"][:46])
        descriptions={"idle":"从搜索开始，收集下一本好书","active":"正在下载","paused":"已请求暂停 · 当前文件可能继续",
                      "stopping":"已请求停止 · 等待安全检查点","done":"任务已结束","stopped":"任务已停止","failed":"任务失败，请查看详情"}
        text=descriptions[state]
        if current or total:
            text+=f"\n{human_size(current)} / {human_size(total)}" if total else f"\n已接收 {human_size(current)} · 总量未知"
        self.task_detail.configure(text=text)
        if active and not total:
            if str(self.home_task_bar.cget("mode"))!="indeterminate":
                self.home_task_bar.configure(mode="indeterminate");self.home_task_bar.start(12)
        else:
            self.home_task_bar.stop();self.home_task_bar.configure(mode="determinate",value=min(100,current/total*100) if total else 0)
        self.home_pause.text="继续" if state=="paused" else "暂停"
        self.home_pause.set_enabled(task["kind"]=="batch" and state in {"active","paused"})
        self.home_stop.set_enabled(task["kind"]=="batch" and state in {"active","paused"})
        self.task_hint.configure(text="单本下载不支持暂停；批量控制见书库页" if task["kind"]=="single" else "批量任务在安全检查点暂停或停止")


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
        self._section_intro(
            self.search_tab,
            "WISDOM SEARCH",
            "检索下载",
            "按书名或 ISBN 查找授权资源，选择结果后下载到本地。",
        )
        controls = ttk.LabelFrame(self.search_tab, text="智慧检索", padding=14)
        controls.pack(fill="x")
        controls.columnconfigure(1, weight=1)
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
        ttk.Button(actions, text="收藏 / 取消收藏", command=self._toggle_selected_favorite).pack(side="left")
        self.search_progress = ttk.Progressbar(actions, length=280, mode="determinate")
        self.search_progress.pack(side="right")
        self.search_status = tk.StringVar(value="等待检索")
        ttk.Label(actions, textvariable=self.search_status).pack(side="right", padx=10)

    def _build_batch_tab(self) -> None:
        self._section_intro(
            self.batch_tab,
            "KNOWLEDGE GARDEN",
            "模糊建库",
            "组合主题、附加关键词和匹配阈值，按目标容量培育你的知识林。",
        )
        form = ttk.LabelFrame(self.batch_tab, text="知识林参数", padding=14)
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
            font=TYPOGRAPHY["mono"],
            background=PALETTE["forest_950"],
            foreground="#DDE8D0",
            insertbackground=PALETTE["gold_soft"],
            selectbackground=PALETTE["forest_700"],
            selectforeground="#FFFDF2",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#416A58",
            padx=12,
            pady=10,
        )
        log_scroll = ttk.Scrollbar(log_frame, command=self.batch_log.yview)
        self.batch_log.configure(yscrollcommand=log_scroll.set)
        self.batch_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _build_favorites_tab(self) -> None:
        self._section_intro(
            self.favorites_tab,
            "COLLECTED WISDOM",
            "收藏",
            "保存书目元数据；已下载的条目可直接阅读，其他条目可继续下载。",
        )
        actions = ttk.Frame(self.favorites_tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="打开 / 下载", style="Accent.TButton", command=self._open_or_download_favorite).pack(side="left")
        ttk.Button(actions, text="打开详情页", command=self._open_favorite_source).pack(side="left", padx=8)
        ttk.Button(actions, text="取消收藏", command=self._remove_favorite).pack(side="left")
        columns = ("title", "author", "format", "year", "state", "time")
        self.favorites_tree = ttk.Treeview(self.favorites_tab, columns=columns, show="headings", selectmode="browse")
        labels = (("title", "书名", 320), ("author", "作者", 180), ("format", "格式", 70),
                  ("year", "年份", 70), ("state", "本地状态", 100), ("time", "收藏时间", 180))
        for key, label, width in labels:
            self.favorites_tree.heading(key, text=label)
            self.favorites_tree.column(key, width=width, stretch=key in {"title", "author"})
        scrollbar = ttk.Scrollbar(self.favorites_tab, command=self.favorites_tree.yview)
        self.favorites_tree.configure(yscrollcommand=scrollbar.set)
        self.favorites_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.favorites_tree.bind("<Double-1>", lambda _: self._open_or_download_favorite())
        self.favorite_books: dict[str, Book] = {}
        self._load_favorites()

    def _build_history_tab(self) -> None:
        self._section_intro(
            self.history_tab,
            "ARCHIVE TRAIL",
            "下载历史",
            "查看每一次检索与归档的状态、大小、本地路径和异常记录。",
        )
        actions = ttk.Frame(self.history_tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="刷新", command=self._load_history).pack(side="left")
        ttk.Button(actions, text="打开文件", style="Accent.TButton", command=self._open_history_file).pack(side="left", padx=8)
        ttk.Button(actions, text="打开所在目录", command=self._open_history_folder).pack(side="left")
        ttk.Button(actions, text="收藏 / 取消收藏", command=self._toggle_history_favorite).pack(side="left", padx=8)
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

    def _build_reading_tab(self) -> None:
        self._section_intro(
            self.reading_tab,
            "READING TRAIL",
            "阅读记录",
            "继续本地阅读；进度只来自内置阅读器，系统阅读器不推测页码。",
        )
        actions = ttk.Frame(self.reading_tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="继续阅读", style="Accent.TButton", command=self._continue_reading).pack(side="left")
        ttk.Button(actions, text="打开所在目录", command=self._open_reading_folder).pack(side="left", padx=8)
        ttk.Button(actions, text="刷新", command=self._load_reading_history).pack(side="left")
        columns = ("time", "title", "format", "progress", "count", "path")
        self.reading_tree = ttk.Treeview(self.reading_tab, columns=columns, show="headings", selectmode="browse")
        labels = (("time", "最近阅读", 180), ("title", "书名", 280), ("format", "格式", 70),
                  ("progress", "内置进度", 100), ("count", "打开次数", 80), ("path", "本地路径", 360))
        for key, label, width in labels:
            self.reading_tree.heading(key, text=label)
            self.reading_tree.column(key, width=width, stretch=key in {"title", "path"})
        scrollbar = ttk.Scrollbar(self.reading_tab, command=self.reading_tree.yview)
        self.reading_tree.configure(yscrollcommand=scrollbar.set)
        self.reading_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.reading_tree.bind("<Double-1>", lambda _: self._continue_reading())
        self.reading_rows = {}
        self._load_reading_history()

    def _build_settings_tab(self) -> None:
        self._section_intro(
            self.settings_tab,
            "SETTINGS & ACCESS",
            "设置与授权",
            "统一管理来源入口、保存目录、浏览器兼容策略与请求节奏。",
        )
        frame = ttk.LabelFrame(self.settings_tab, text="运行参数与授权确认", padding=16)
        frame.pack(fill="x")
        frame.columnconfigure(1, weight=1)
        self.setting_output = tk.StringVar(value=self.settings.output_dir)
        self.setting_base = tk.StringVar(value=self.settings.base_url)
        self.setting_delay = tk.DoubleVar(value=self.settings.request_delay)
        self.setting_page_timeout = tk.IntVar(value=self.settings.page_timeout)
        self.setting_download_timeout = tk.IntVar(value=self.settings.download_timeout)
        self.setting_authorized = tk.BooleanVar(value=self.settings.authorization_confirmed)
        self.setting_auto_source = tk.BooleanVar(value=self.settings.auto_update_source)
        self.setting_browser_mode = tk.StringVar(
            value=BROWSER_MODE_LABELS.get(self.settings.browser_mode, BROWSER_MODE_LABELS["auto"])
        )
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
        ttk.Label(frame, text="浏览器模式").grid(row=5, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.setting_browser_mode,
            values=tuple(BROWSER_MODE_LABELS.values()),
            state="readonly",
        ).grid(row=5, column=1, sticky="ew", pady=6)
        ttk.Checkbutton(
            frame,
            text="启动时自动检测并填充项目维护的新站点入口",
            variable=self.setting_auto_source,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(
            frame,
            text="我确认仅下载已获授权、开放许可或公版内容，并遵守来源站点规则",
            variable=self.setting_authorized,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=6)
        buttons = ttk.Frame(frame)
        buttons.grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text="保存设置", style="Accent.TButton", command=self._save_settings).pack(side="left")
        self.source_check_button = ttk.Button(
            buttons,
            text="立即检测新入口",
            command=lambda: self._start_source_check(manual=True),
        )
        self.source_check_button.pack(side="left", padx=8)
        self.source_status = tk.StringVar(value="尚未检测远程入口清单")
        ttk.Label(frame, textvariable=self.source_status, style="Hint.TLabel").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            self.settings_tab,
            text="说明：自动兼容模式先使用无窗口 Chrome；若站点拒绝该模式，则改用隐藏的普通 Chrome，桌面和任务栏均不显示浏览器窗口。程序只启用一个下载任务，“暂停”会在当前文件完成后生效。历史数据库和浏览器专用配置位于本机 LocalAppData。",
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

    def _start_source_check(self, manual: bool = False) -> None:
        if self.source_check_active:
            if manual:
                messagebox.showinfo("正在检测", "站点入口检测正在后台进行。")
            return
        if self.busy_lock.locked():
            if manual:
                messagebox.showinfo("任务进行中", "请等待当前检索或下载任务完成后再检测。")
            else:
                self.root.after(3000, self._start_source_check)
            return
        if not manual and not self.settings.auto_update_source:
            self.source_status.set("自动检测已关闭")
            return
        if not manual and not source_check_due(self.settings.source_checked_at):
            self.source_status.set(f"当前入口：{self.settings.base_url}")
            return
        if managed_source_origin(self.settings.base_url) is None:
            self.source_status.set("当前为自定义来源，自动检测不会覆盖")
            if manual:
                messagebox.showinfo("保留自定义来源", "当前站点入口不是项目维护来源，已保留原设置。")
            return

        original_url = normalize_base_url(self.settings.base_url)
        self.source_check_active = True
        self.source_check_button.configure(state="disabled")
        self.source_status.set("正在检测项目维护的最新入口…")

        def target() -> None:
            try:
                result = discover_preferred_source(original_url)
                self._post("source_check_done", (result, manual))
            except SourceDiscoveryError as error:
                self._post("source_check_error", (str(error), manual))

        threading.Thread(target=target, name="bookbuilder-source-check", daemon=True).start()

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

    @staticmethod
    def _book_from_row(row) -> Book:
        keys = set(row.keys())
        return Book(
            source_id=row["source_id"],
            title=row["title"],
            author=row["author"] or "",
            publisher=row["publisher"] or "",
            year=row["year"] or "",
            language=row["language"] or "",
            file_format=row["file_format"] or "",
            size_bytes=int(row["expected_bytes"] or 0),
            detail_url=row["detail_url"] or "",
            cover_url=(row["cover_url"] or "") if "cover_url" in keys else "",
        )

    def _toggle_selected_favorite(self) -> None:
        book = self._selected_book()
        if not book:
            messagebox.showinfo("未选择", "请先选择一条检索结果。")
            return
        added = self.database.toggle_favorite(book)
        self.search_status.set(("已收藏：" if added else "已取消收藏：") + book.title)
        self._load_favorites()

    def _download_selected(self) -> None:
        book = self._selected_book()
        if not book:
            messagebox.showinfo("未选择", "请先选择一条检索结果。")
            return
        output = self.search_output.get().strip()
        if not output:
            messagebox.showwarning("缺少目录", "请选择保存目录。")
            return
        self._download_book(book, output, self.search_query.get().strip())

    def _download_book(self, book: Book, output: str, query: str) -> None:
        if not self._ensure_authorized():
            return
        self.search_status.set(f"准备下载：{book.title}")

        def progress(current: int, total: int) -> None:
            self._post("single_progress", (current, total, book.title))

        def operation() -> None:
            result = self.downloads.download(book, output, query, progress=progress)
            self._post("single_done", (book, result))

        if self._run_worker("download", operation):
            self._set_home_task(kind="single",state="active",title=book.title,current=0,total=book.size_bytes)

    def _open_selected_source(self) -> None:
        book = self._selected_book()
        if book:
            webbrowser.open(book.detail_url)

    def _favorite_book(self) -> Book | None:
        selected = self.favorites_tree.selection()
        return self.favorite_books.get(selected[0]) if selected else None

    def _load_favorites(self) -> None:
        if not hasattr(self, "favorites_tree"):
            return
        self.favorite_books.clear()
        for item in self.favorites_tree.get_children():
            self.favorites_tree.delete(item)
        for index, row in enumerate(self.database.favorites()):
            book = self._book_from_row(row)
            iid = f"favorite-{index}"
            self.favorite_books[iid] = book
            completed = self.database.completed(book.source_id)
            local = bool(completed and completed["local_path"] and Path(completed["local_path"]).is_file())
            self.favorites_tree.insert(
                "", "end", iid=iid,
                values=(book.title, book.author, book.file_format, book.year, "已下载" if local else "未下载", row["created_at"]),
            )

    def _remove_favorite(self) -> None:
        book = self._favorite_book()
        if not book:
            messagebox.showinfo("未选择", "请先选择一条收藏。")
            return
        self.database.toggle_favorite(book)
        self._load_favorites()

    def _open_favorite_source(self) -> None:
        book = self._favorite_book()
        if book and book.detail_url:
            webbrowser.open(book.detail_url)

    def _open_or_download_favorite(self) -> None:
        book = self._favorite_book()
        if not book:
            messagebox.showinfo("未选择", "请先选择一条收藏。")
            return
        completed = self.database.completed(book.source_id)
        if completed and completed["local_path"] and Path(completed["local_path"]).is_file():
            self._open_download(completed)
        else:
            self._download_book(book, self.settings.output_dir, "收藏")

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
        else:
            self._set_home_task(kind="batch",state="active",title=f"主题书库 · {query}",current=0,total=0)

    def _toggle_pause(self) -> None:
        if self.resume_event.is_set():
            self.resume_event.clear()
            self.pause_button.configure(text="继续")
            self._append_log("已请求暂停；当前文件会先完成。")
            self._set_home_task(state="paused")
        else:
            self.resume_event.set()
            self.pause_button.configure(text="暂停")
            self._append_log("继续建库。")
            self._set_home_task(state="active")

    def _stop_batch(self) -> None:
        self.cancel_event.set()
        self.resume_event.set()
        self._append_log("已请求停止；当前文件会先完成。")
        self._set_home_task(state="stopping")

    def _append_log(self, text: str) -> None:
        self.batch_log.configure(state="normal")
        self.batch_log.insert("end", text + "\n")
        self.batch_log.see("end")
        self.batch_log.configure(state="disabled")

    def _handle_batch_event(self, event: str, payload: dict[str, object]) -> None:
        if event == "search":
            self._append_log(f"检索第 {payload['page']} 页；已扫描 {payload['scanned']} 条")
            self._set_home_task(kind="batch",title=f"正在检索第 {payload['page']} 页",current=0,total=0)
        elif event == "book_start":
            book = payload["book"]
            assert isinstance(book, Book)
            self._append_log(f"下载：{book.title} [{book.file_format}, {human_size(book.size_bytes)}, {book.match_score}%]")
            self._set_home_task(kind="batch",title=book.title,current=0,total=book.size_bytes)
        elif event == "progress":
            base = int(payload["bytes"])
            current = int(payload["current"])
            self.batch_progress.configure(value=min(self._batch_target_bytes, base + current))
            self._set_home_task(current=current,total=int(payload.get("expected",0)))
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
            self._set_home_task(title=f"下载失败 · {book.title}",current=0,total=0)
        elif event == "done":
            self.pause_button.configure(state="disabled", text="暂停")
            self.stop_button.configure(state="disabled")
            suffix = "（用户停止）" if payload.get("cancelled") else ""
            self.batch_summary.set(
                f"完成{suffix}：扫描 {payload['scanned']}，下载 {payload['downloaded']}，{human_size(int(payload['bytes']))}"
            )
            self._append_log(self.batch_summary.get())
            self._set_home_task(state="stopped" if payload.get("cancelled") else "done",title="批量任务已停止" if payload.get("cancelled") else "批量任务结束",current=int(payload["bytes"]),total=int(payload["bytes"]))

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
        self._refresh_home()
        self._load_favorites()
        self._load_reading_history()

    def _selected_history_row(self):
        selected = self.history_tree.selection()
        return self.database.download(int(selected[0])) if selected else None

    def _history_path(self) -> Path | None:
        row = self._selected_history_row()
        return Path(row["local_path"]) if row and row["local_path"] else None

    def _open_history_file(self) -> None:
        row = self._selected_history_row()
        if row and row["local_path"] and Path(row["local_path"]).is_file():
            self._open_download(row)
        else:
            messagebox.showinfo("文件不存在", "所选记录没有可用的本地文件。")

    def _open_history_folder(self) -> None:
        path = self._history_path()
        if path and path.parent.is_dir():
            os.startfile(path.parent)
        else:
            messagebox.showinfo("目录不存在", "所选记录没有可用的本地目录。")

    def _toggle_history_favorite(self) -> None:
        row = self._selected_history_row()
        if not row:
            messagebox.showinfo("未选择", "请先选择一条下载记录。")
            return
        added = self.database.toggle_favorite(self._book_from_row(row))
        self.global_status.set(("已收藏：" if added else "已取消收藏：") + row["title"])
        self._load_favorites()

    def _open_download(self, row) -> None:
        path = Path(row["local_path"] or "")
        if not path.is_file():
            messagebox.showinfo("文件不存在", "记录对应的本地文件已移动或不存在。")
            return
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            try:
                return ReaderWindow(self.root, self.database, row, self._reading_saved)
            except ReaderError as error:
                messagebox.showerror("无法阅读", str(error))
            return
        try:
            os.startfile(path)
        except OSError as error:
            messagebox.showerror("打开失败", str(error))
            return
        self.database.record_reading(int(row["id"]))
        self._reading_saved()

    def _reading_saved(self) -> None:
        self._load_reading_history()
        self._refresh_home()

    def _load_reading_history(self) -> None:
        if not hasattr(self, "reading_tree"):
            return
        self.reading_rows.clear()
        for item in self.reading_tree.get_children():
            self.reading_tree.delete(item)
        for row in self.database.reading_history():
            iid=f"reading-{row['id']}"
            self.reading_rows[iid]=row
            suffix=Path(row["local_path"] or "").suffix.lower()
            progress=f"{round(float(row['progress'])*100)}%" if suffix in SUPPORTED_SUFFIXES else "外部阅读"
            self.reading_tree.insert(
                "", "end", iid=iid,
                values=(row["last_opened"], row["title"], row["file_format"], progress, row["open_count"], row["local_path"] or ""),
            )

    def _selected_reading_row(self):
        selected=self.reading_tree.selection()
        return self.reading_rows.get(selected[0]) if selected else None

    def _continue_reading(self) -> None:
        row=self._selected_reading_row()
        if row:
            self._open_download(row)
        else:
            messagebox.showinfo("未选择", "请先选择一条阅读记录。")

    def _open_reading_folder(self) -> None:
        row=self._selected_reading_row()
        path=Path(row["local_path"] or "") if row else None
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
        previous_base_url = self.settings.base_url
        self.settings.base_url = normalize_base_url(self.setting_base.get())
        if self.settings.base_url != previous_base_url:
            self.settings.source_checked_at = 0.0
        self.setting_base.set(self.settings.base_url)
        self.settings.request_delay = delay
        self.settings.page_timeout = page_timeout
        self.settings.download_timeout = download_timeout
        self.settings.authorization_confirmed = bool(self.setting_authorized.get())
        self.settings.auto_update_source = bool(self.setting_auto_source.get())
        previous_browser_mode = self.settings.browser_mode
        self.settings.browser_mode = BROWSER_MODE_VALUES.get(self.setting_browser_mode.get(), "auto")
        if self.settings.browser_mode != previous_browser_mode:
            self.browser.apply_configured_mode()
        self.settings.save()
        self.search_output.set(self.settings.output_dir)
        self.batch_output.set(self.settings.output_dir)
        mode_label = BROWSER_MODE_LABELS[self.settings.browser_mode]
        messagebox.showinfo("已保存", f"设置已保存。浏览器模式：{mode_label}。")

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
                    self.shelf_mode="search"
                    self._refresh_home()
                    if self.settings.browser_mode == "auto" and self.browser.runtime_mode == "compatibility":
                        self.global_status.set("站点拒绝完全无窗口模式，已自动改用隐藏兼容模式。")
                elif event == "single_progress":
                    current, total, title = payload
                    self._set_home_task(kind="single",state="active",title=title,current=current,total=total)
                    if total:
                        self.search_progress.configure(maximum=total, value=min(current, total), mode="determinate")
                        self.search_status.set(f"{title}：{human_size(current)} / {human_size(total)}")
                    else:
                        self.search_progress.configure(mode="indeterminate")
                        self.search_progress.start(10)
                        self.search_status.set(f"{title}：{human_size(current)}")
                elif event == "single_done":
                    book, result = payload
                    self._set_home_task(kind="single",state="done",title=("已有本地文件 · " if result.skipped else "下载完成 · ")+book.title,current=result.size_bytes,total=result.size_bytes)
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
                    if label in {"batch","download"}:
                        self._set_home_task(state="failed",title="任务失败，请查看原页面提示")
                    self.global_status.set(f"{label} 失败：{error}")
                    if label == "search":
                        self.search_status.set(f"检索失败：{error}")
                    messagebox.showerror("任务失败", str(error))
                elif event == "source_check_done":
                    result, manual = payload
                    assert isinstance(result, SourceDiscoveryResult)
                    self.source_check_active = False
                    self.source_check_button.configure(state="normal")
                    field_value = normalize_base_url(self.setting_base.get())
                    if field_value != result.current_url:
                        self.source_status.set("输入框内容已变化，本次检测结果未覆盖")
                    else:
                        self.settings.source_checked_at = result.checked_at
                        if result.changed:
                            self.settings.base_url = result.preferred_url
                            self.setting_base.set(result.preferred_url)
                            self.settings.save()
                            self.source_status.set(f"已自动更新入口：{result.preferred_url}")
                            self.global_status.set(f"站点入口已更新：{result.preferred_url}")
                            if manual:
                                messagebox.showinfo("检测完成", f"已更新并保存站点入口：\n{result.preferred_url}")
                        else:
                            self.settings.save()
                            self.source_status.set(f"已是最新入口：{result.preferred_url}")
                            if manual:
                                messagebox.showinfo("检测完成", "当前已经是项目维护的最新站点入口。")
                elif event == "source_check_error":
                    error, manual = payload
                    self.source_check_active = False
                    self.source_check_button.configure(state="normal")
                    self.source_status.set(f"检测失败，继续使用当前入口：{self.settings.base_url}")
                    if manual:
                        messagebox.showwarning("检测失败", str(error))
                elif event == "worker_idle":
                    self.search_button.configure(state="normal")
                    if self.settings.base_url != normalize_base_url(self.setting_base.get()):
                        self.setting_base.set(self.settings.base_url)
                        self.source_status.set(f"已从站点跳转更新入口：{self.settings.base_url}")
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
    prepare_tk_runtime()
    root = tk.Tk()
    BookBuilderApp(root)
    root.mainloop()
