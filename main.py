from __future__ import annotations

import argparse
import json
import os
import sys

from bookbuilder import __version__


def smoke_test() -> int:
    from bookbuilder.browser import find_chrome
    from bookbuilder.config import Settings
    from bookbuilder.database import HistoryDatabase

    settings = Settings.load()
    database = HistoryDatabase()
    payload = {
        "app_version": __version__,
        "python": sys.version.split()[0],
        "chrome": str(find_chrome()),
        "database": str(database.path),
        "base_url": settings.base_url,
    }
    if sys.stdout is not None:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="授权书籍下载与模糊建库工具")
    parser.add_argument("--smoke-test", action="store_true", help="验证运行时后退出")
    parser.add_argument("--version", action="store_true", help="显示版本后退出")
    args = parser.parse_args()
    if args.version:
        if sys.stdout is not None:
            print(__version__)
        return 0
    if args.smoke_test or os.environ.get("BOOKBUILDER_SMOKE_TEST") == "1":
        return smoke_test()
    from bookbuilder.gui import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
