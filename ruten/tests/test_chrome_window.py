"""ensure_live_window 離線測試：以假 driver 模擬 Chrome 啟動競態。"""

import unittest

from selenium.common.exceptions import NoSuchWindowException, WebDriverException

from chrome_window import ensure_live_window


class FakeSwitchTo:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.switched.append(handle)
        self.driver.stale = False
        self.driver._current_error = None


class FakeDriver:
    def __init__(self, stale=False, handle_batches=None, current_error=None):
        self.stale = stale
        self.switched = []
        self.switch_to = FakeSwitchTo(self)
        # 每次讀 window_handles 依序回傳一批，用完後固定回傳最後一批
        self._batches = list(handle_batches or [["h1"]])
        self._current_error = current_error

    @property
    def current_window_handle(self):
        if self._current_error:
            raise self._current_error
        if self.stale:
            raise NoSuchWindowException("target window already closed")
        return "h1"

    @property
    def window_handles(self):
        return self._batches.pop(0) if len(self._batches) > 1 else self._batches[0]


class EnsureLiveWindowTests(unittest.TestCase):
    def test_healthy_handle_is_not_switched(self):
        driver = FakeDriver()
        ensure_live_window(driver, poll=0)
        self.assertEqual(driver.switched, [])

    def test_stale_handle_switches_to_last_handle(self):
        driver = FakeDriver(stale=True, handle_batches=[["a", "b"]])
        ensure_live_window(driver, poll=0)
        self.assertEqual(driver.switched, ["b"])

    def test_handles_appear_after_empty_polls(self):
        driver = FakeDriver(stale=True, handle_batches=[[], [], ["late"]])
        ensure_live_window(driver, timeout=5, poll=0)
        self.assertEqual(driver.switched, ["late"])

    def test_timeout_raises_when_no_handle(self):
        driver = FakeDriver(stale=True, handle_batches=[[]])
        with self.assertRaises(RuntimeError):
            ensure_live_window(driver, timeout=0.05, poll=0.01)

    def test_no_such_window_webdriver_exception_is_recovered(self):
        driver = FakeDriver(
            stale=True,
            handle_batches=[["x"]],
            current_error=WebDriverException("unknown error: no such window: web view not found"),
        )
        ensure_live_window(driver, poll=0)
        self.assertEqual(driver.switched, ["x"])

    def test_other_errors_propagate(self):
        driver = FakeDriver(current_error=WebDriverException("chrome not reachable"))
        with self.assertRaises(WebDriverException):
            ensure_live_window(driver, poll=0)


if __name__ == "__main__":
    unittest.main()
