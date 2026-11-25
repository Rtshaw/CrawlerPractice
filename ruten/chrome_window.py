# -*- coding: utf-8 -*-
"""Chrome 啟動競態的視窗恢復工具（不含任何付款邏輯）。"""

from __future__ import annotations

import time

from selenium.common.exceptions import NoSuchWindowException, WebDriverException


def _is_no_such_window(exc: WebDriverException) -> bool:
    # 部分版本會以一般 WebDriverException 回報，只認訊息含 "no such window" 的情況
    return isinstance(exc, NoSuchWindowException) or "no such window" in (
        getattr(exc, "msg", None) or str(exc)
    ).lower()


def ensure_live_window(
    driver, timeout: float = 10.0, poll: float = 0.25, settle: float = 1.5
) -> None:
    """確認 driver 綁定的視窗有效，且在 settle 秒內持續有效、handle 集合不變。

    uc 以 detached 方式啟動 Chrome，chromedriver 附加後，初始 target 可能被替換，
    造成 current_window_handle 丟出 no such window，但 window_handles 仍有有效 handle；
    替換的時間點也可能落在單次檢查之後，所以必須通過穩定期。
    期間失效就切到最後一個 handle 並重新計時；總逾時仍不穩定則丟 RuntimeError。
    其他錯誤一律往外丟，不吞掉。
    """
    deadline = time.monotonic() + timeout
    stable_since = None  # 目前這批 handle 開始穩定的時間
    last_handles = None
    while True:
        try:
            driver.current_window_handle
            handles = list(driver.window_handles)
            alive = True
        except WebDriverException as exc:
            if not _is_no_such_window(exc):
                raise
            handles = list(driver.window_handles)
            alive = False

        now = time.monotonic()
        if alive:
            if handles != last_handles:
                # handle 集合有變動，重新計時
                last_handles, stable_since = handles, now
            elif now - stable_since >= settle:
                return
        elif handles:
            driver.switch_to.window(handles[-1])
            last_handles, stable_since = None, None
        else:
            last_handles, stable_since = None, None

        if now >= deadline:
            raise RuntimeError(f"Chrome 啟動後 {timeout} 秒內視窗仍不穩定或沒有有效的 handle")
        time.sleep(poll)


def retry_on_stale_window(driver, action, attempts: int = 3):
    """執行 action()；遇到 no such window 時先恢復視窗再重試，最多 attempts 次。

    其他錯誤不重試；次數用盡則丟出最後一次的例外。
    """
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except WebDriverException as exc:
            if not _is_no_such_window(exc) or attempt == attempts:
                raise
            ensure_live_window(driver)
