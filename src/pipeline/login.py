"""Save YOUR Threads login session for `python -m src.pipeline.run --login`.

    python -m src.pipeline.login

What happens:
  1. A visible Chromium window opens on this computer, on the Threads login page.
  2. You log in by hand (password, 2FA, any "is this you?" step). Type nothing into this terminal.
  3. Back here, press Enter. Only Playwright's `storage_state` (cookies + local storage of that browser) is saved to
     .secrets/threads_state.json (git-ignored, file mode 600).

This program never asks for, reads, or stores a username or password. The saved file works like a logged-in
session: keep it private, and when you are done log out of all devices (Instagram / Threads: Settings ->
Accounts Centre -> Password and security -> Where you're logged in) and delete .secrets/threads_state.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import config
from .scraper import default_executable


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only from the start
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.pipeline.login", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", type=Path, default=config.STATE_PATH, help=f"where to save (default {config.STATE_PATH})")
    ap.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)  # tests only: you need a visible window to log in
    args = ap.parse_args(argv)

    with sync_playwright() as pw:
        kw: dict = {"headless": args.headless}
        exe = default_executable()
        if exe:
            kw["executable_path"] = exe
        browser = pw.chromium.launch(**kw)
        ctx = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(f"{config.THREADS_BASE}/login", wait_until="domcontentloaded")
        print("\n已開啟 Threads 登入頁。請在瀏覽器視窗裡自己登入（含二階段驗證）；不要在這個終端機輸入任何帳密。")
        print("登入完成、看到自己的首頁後，回到這裡按 Enter 儲存登入狀態（Ctrl+C 取消）。")
        input()
        try:
            state = ctx.storage_state()
        except Exception as e:  # noqa: BLE001 - usually: the browser window was closed before Enter
            print(f"讀不到瀏覽器的登入狀態（視窗是不是先關掉了？）：{e}")
            return 1
        names = {c["name"] for c in state.get("cookies", [])}
        if "sessionid" not in names:
            print("警告：沒有看到 sessionid cookie，可能還沒登入完成。仍會儲存；若之後 run --login 提示登入失效，請重新執行這個指令。")
        save_state(state, args.state)
        browser.close()
    print(f"已儲存登入狀態到 {args.state}（只含 cookies 與 local storage，不含密碼）。")
    print("用完後請登出所有裝置並刪除這個檔案。下一步：python -m src.pipeline.run --login --add <帳號...> --as <你的 dashboard email>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
