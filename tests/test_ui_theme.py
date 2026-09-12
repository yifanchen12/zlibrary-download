from __future__ import annotations

import unittest
import time
import tempfile
import tkinter as tk
from unittest.mock import Mock, patch
from pathlib import Path

from bookbuilder.gui import SUMERU_THEME, BookBuilderApp, prepare_tk_runtime
from bookbuilder.config import Settings
from bookbuilder.database import HistoryDatabase
from bookbuilder.models import Book


class SumeruThemeTests(unittest.TestCase):
    def test_theme_tokens_and_original_assets_are_available(self) -> None:
        root = Path(__file__).resolve().parents[1]
        header = root / "assets" / "nahida_header.png"
        icon = root / "assets" / "app_icon.ico"

        self.assertEqual(SUMERU_THEME["forest_900"], "#1D493C")
        self.assertIn("gold", SUMERU_THEME)
        self.assertTrue(header.is_file())
        self.assertTrue(icon.is_file())
        self.assertEqual(header.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertFalse((root / "assets" / "furina_header.png").exists())
        self.assertTrue((root / "assets" / "sumeru_palace.png").is_file())


class HomeInteractionTests(unittest.TestCase):
    def test_isolated_home_interactions_and_responsive_layout(self):
        root_dir=Path(__file__).resolve().parents[1]
        output=root_dir/"build"/"ui-check";output.mkdir(parents=True,exist_ok=True)
        prepare_tk_runtime(output/"runtime")
        with tempfile.TemporaryDirectory(dir=output,prefix="synthetic-") as folder:
            base=Path(folder);settings=Settings(output_dir=str(base/"downloads"),base_url="https://example.invalid",authorization_confirmed=True,auto_update_source=False)
            database=HistoryDatabase(base/"history.sqlite3")
            titles=("植物观察笔记","算法与诗","人文漫游","林间的一年","星空里的数学","日常的艺术")
            books=[Book(f"fixture-{i}",title,"示例作者","合成书目","2026","Chinese","PDF",1024,f"https://example.invalid/book/{i}") for i,title in enumerate(titles)]
            browser=Mock();browser.runtime_mode="headless";browser.search.return_value=books
            def download(book,target,**kwargs):
                file=target/(book.title+".pdf");file.write_bytes(b"synthetic UI fixture, not a real PDF")
                kwargs["progress"](file.stat().st_size,file.stat().st_size)
                return file
            browser.download.side_effect=download
            root=tk.Tk();root.withdraw();errors=[]
            root.report_callback_exception=lambda *args:errors.append(args)
            with patch("bookbuilder.gui.Settings.load",return_value=settings),patch("bookbuilder.gui.HistoryDatabase",return_value=database),patch("bookbuilder.gui.BrowserController",return_value=browser),patch.object(BookBuilderApp,"_start_source_check") as discovery,patch("bookbuilder.gui.messagebox.showinfo"),patch("bookbuilder.gui.messagebox.showerror") as error_popup,patch("bookbuilder.gui.messagebox.showwarning"):
                app=BookBuilderApp(root);root.geometry("1600x940");root.deiconify()
                def settle(seconds=.2):
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:root.update();time.sleep(.01)
                    if errors:raise AssertionError(f"Tk callback failed: {errors[0][0].__name__}: {errors[0][1]}")
                def finish():
                    deadline=time.monotonic()+5
                    while app.busy_lock.locked() and time.monotonic()<deadline:settle(.03)
                    self.assertFalse(app.busy_lock.locked());settle(.25)
                try:
                    settle()
                    self.assertEqual(app.shelf_items,[])
                    self.assertFalse(app.read_button.enabled)
                    self.assertEqual(app.shelf_mode,"history")
                    self.assertEqual(len(app.nav_buttons),7)
                    self.assertTrue(all(b.enabled for b in app.nav_buttons))
                    app.search_query.set("植物");app.header_search.invoke();finish()
                    browser.search.assert_called_once_with("植物",1)
                    self.assertEqual(len(app.search_tree.get_children()),6)
                    app._show_page(0);settle();self.assertEqual(len(app.shelf_items),6)
                    self.assertEqual(app.shelf_mode,"search")
                    app._open_shelf_item(0);self.assertEqual(app._selected_book().title,titles[0])
                    app._toggle_selected_favorite();self.assertTrue(database.is_favorite(books[0].source_id))
                    app._show_page(3);settle();self.assertEqual(len(app.favorites_tree.get_children()),1)
                    app._show_page(1);app.search_tree.selection_set("book-0")
                    app._download_selected();finish();self.assertEqual(app.home_task["state"],"done",error_popup.call_args)
                    self.assertEqual(len(database.recent()),1)
                    app._show_page(3);favorite=app.favorites_tree.get_children()[0];app.favorites_tree.selection_set(favorite)
                    self.assertEqual(app.favorites_tree.item(favorite,"values")[4],"已下载")
                    with patch("bookbuilder.gui.os.startfile") as opened:
                        app._open_or_download_favorite();opened.assert_called_once()
                    app._show_page(0);app._toggle_shelf();settle()
                    self.assertEqual(len(app.shelf_items),1)
                    with patch("bookbuilder.gui.os.startfile") as opened:
                        app.read_button.invoke();opened.assert_called_once()
                        self.assertTrue(Path(opened.call_args.args[0]).is_relative_to(base))
                    self.assertEqual(len(database.reading_history()),1)
                    app._show_page(5);settle();self.assertEqual(len(app.reading_tree.get_children()),1)

                    text_book=Book("fixture-text","林间短章","示例作者","合成书目","2026","Chinese","TXT",10,"https://example.invalid/text")
                    text_file=base/"downloads"/"林间短章.txt";text_file.write_text("第一章\n"+("森林里的正文。"*500),encoding="utf-8")
                    text_id=database.begin(text_book,"synthetic");database.complete(text_id,str(text_file),text_file.stat().st_size)
                    reader=app._open_download(database.download(text_id));settle()
                    reader.text.yview_moveto(1);settle();reader.close();settle()
                    self.assertGreater(float(database.reading_state(text_id)["progress"]),.9)
                    app.category_buttons[2].event_generate("<Button-1>");settle()
                    self.assertEqual(app.batch_query.get(),"计算机科学")
                    self.assertEqual(app.notebook.index(app.notebook.select()),2)
                    app._batch_target_bytes=10000
                    app._set_home_task(kind="batch",state="active",title="合成任务",current=0,total=0)
                    app._post("batch_event",("progress",{"book":books[0],"current":1500,"expected":3000,"bytes":0}));settle()
                    self.assertEqual(float(app.home_task_bar.cget("value")),50)
                    app.home_pause.invoke();self.assertFalse(app.resume_event.is_set())
                    self.assertEqual(app.home_task["state"],"paused")
                    app.home_pause.invoke();self.assertTrue(app.resume_event.is_set())
                    app.home_stop.invoke();self.assertTrue(app.cancel_event.is_set())
                    self.assertEqual(app.home_task["state"],"stopping")
                    app._post("batch_event",("done",{"cancelled":True,"scanned":1,"downloaded":0,"bytes":0}));settle()
                    self.assertEqual(app.home_task["state"],"stopped")
                    self.assertIn("已停止",app.task_detail.cget("text"))
                    app._post("worker_error",("batch","synthetic failure",""));settle()
                    self.assertEqual(app.home_task["state"],"failed")
                    app._post("single_progress",(4096,0,"合成任务"));settle()
                    self.assertIn("总量未知",app.task_detail.cget("text"))
                    self.assertEqual(str(app.home_task_bar.cget("mode")),"indeterminate")

                    # Populate only generated local records for the reference screenshot.
                    for book in books[1:]:
                        file=base/"downloads"/(book.title+".pdf");file.write_bytes(b"synthetic")
                        row=database.begin(book,"synthetic");database.complete(row,str(file),file.stat().st_size)
                    app._load_history();app.shelf_mode="history";app._show_page(0)
                    app.search_query.set("");app._set_home_task(kind="batch",state="active",title="植物观察笔记 · 合成任务",current=620000,total=1000000)
                    app.global_status.set("界面验证 · 合成书目与进度，不含私人书库或真实下载")
                    root.focus_force();app.nav_buttons[0].focus_set();settle(.35)
                    from PIL import ImageGrab
                    import ctypes
                    from ctypes import wintypes
                    get=ctypes.windll.user32.GetAncestor;get.argtypes=[wintypes.HWND,wintypes.UINT];get.restype=wintypes.HWND
                    handle=get(root.winfo_id(),2)
                    ImageGrab.grab(window=handle).save(output/"home-wide.png")
                    self.assertFalse(app._compact_home)
                    root.geometry("1100x760");settle(.35)
                    self.assertTrue(app._compact_home)
                    ImageGrab.grab(window=handle).save(output/"home-minimum.png")
                    home=app.page_views[0];home.canvas.yview_moveto(1);settle()
                    self.assertTrue(app.home_stop.winfo_ismapped())
                    self.assertLess(app.home_stop.winfo_rooty()+app.home_stop.winfo_height(),root.winfo_rooty()+root.winfo_height())
                    ImageGrab.grab(window=handle).save(output/"home-minimum-bottom.png")
                    for index in range(1,7):
                        app._show_page(index);settle()
                        self.assertTrue(app.page_views[index].horizontal.winfo_ismapped())
                        app.page_views[index].canvas.yview_moveto(1);settle()
                        if index in (1,3,5,6):ImageGrab.grab(window=handle).save(output/f"page-{index}-minimum-bottom.png")
                    self.assertFalse(errors)
                    browser.download.assert_called_once()
                finally:
                    for job in root.tk.call("after","info"):
                        root.tk.call("after", "cancel", job)
                    app.browser.close();root.destroy()


if __name__ == "__main__":
    unittest.main()
