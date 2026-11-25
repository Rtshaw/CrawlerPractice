# -*- coding: utf-8 -*-
"""Chrome 啟動競態的視窗恢復工具（不含任何付款邏輯）。"""

from __future__ import annotations

import time

from selenium.common.exceptions import NoSuchWindowException, WebDriverException


def _is_no_such_window(exc: WebDriverException) -> bool:
    # 部分版本會以一般 WebDriverException 回報，只認訊息含 "no such window" 的情況
    return "no such window" in (exc.msg or str(exc)).lower()


def ensure_live_window(driver, timeout: float = 5.0, poll: float = 0.25) -> None:
    """確認 driver 綁定的視窗有效；若初始 target 在啟動期間被 Chrome 換掉，改切到最後一個有效 handle。

    uc 以 detached 方式啟動 Chrome，chromedriver 附加後，初始 target 可能被替換，
    造成 current_window_handle 丟出 no such window，但 window_handles 仍有有效 handle。
    其他錯誤一律往外丟，不吞掉。
    """
    try:
        driver.current_window_handle
        return
    except NoSuchWindowException:
        pass
    except WebDriverException as exc:
        if not _is_no_such_window(exc):
            raise

    deadline = time.monotonic() + timeout
    while True:
        handles = driver.window_handles
        if handles:
            driver.switch_to.window(handles[-1])
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Chrome 啟動後 {timeout} 秒內仍找不到有效的視窗 handle")
        time.sleep(poll)
