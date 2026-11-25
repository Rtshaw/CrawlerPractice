"""ensure_live_window 離線測試：以假 driver 模擬 Chrome 啟動競態。"""

import unittest

from selenium.common.exceptions import NoSuchWindowException, WebDriverException

from unittest.mock import patch

import chrome_window
from chrome_window import ensure_live_window, retry_on_stale_window


class FakeClock:
    """假時鐘：sleep 只推進虛擬時間，測試不會真的等待。"""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.01)


def setUpModule():
    global _patcher
    _patcher = patch.object(chrome_window, "time", FakeClock())
    _patcher.start()


def tearDownModule():
    _patcher.stop()


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

    def test_handle_going_stale_during_settle_switches_and_restarts_timer(self):
        # 穩定期內第一次檢查後 handle 失效：必須再切換一次，且穩定期重新計時
        class FlakyDriver(FakeDriver):
            reads = 0

            @property
            def current_window_handle(self):
                FlakyDriver.reads += 1
                if FlakyDriver.reads == 3:
                    raise NoSuchWindowException("replaced")
                return "h1"

        driver = FlakyDriver(handle_batches=[["a"]])
        start = chrome_window.time.now
        ensure_live_window(driver, settle=1.5, poll=0.25)
        self.assertEqual(driver.switched, ["a"])
        # 重新計時，所以總耗時超過單一 settle
        self.assertGreater(chrome_window.time.now - start, 1.5)

    def test_unstable_handles_until_timeout_raises(self):
        class ChurnDriver(FakeDriver):
            n = 0

            @property
            def window_handles(self):
                ChurnDriver.n += 1
                return [f"h{ChurnDriver.n}"]

        with self.assertRaises(RuntimeError):
            ensure_live_window(ChurnDriver(), timeout=3, settle=1.5, poll=0.25)


class RetryOnStaleWindowTests(unittest.TestCase):
    def test_retries_after_first_no_such_window(self):
        driver = FakeDriver(stale=True, handle_batches=[["a"]])
        calls = []

        def action():
            calls.append(1)
            if len(calls) == 1:
                raise NoSuchWindowException("gone")
            return "ok"

        self.assertEqual(retry_on_stale_window(driver, action), "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(driver.switched, ["a"])

    def test_exhausted_attempts_raise(self):
        driver = FakeDriver(handle_batches=[["a"]])
        calls = []

        def action():
            calls.append(1)
            raise NoSuchWindowException("gone")

        with self.assertRaises(NoSuchWindowException):
            retry_on_stale_window(driver, action, attempts=3)
        self.assertEqual(len(calls), 3)

    def test_other_errors_not_retried(self):
        calls = []

        def action():
            calls.append(1)
            raise WebDriverException("chrome not reachable")

        with self.assertRaises(WebDriverException):
            retry_on_stale_window(FakeDriver(), action)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
