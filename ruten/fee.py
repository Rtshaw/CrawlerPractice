# -*- coding: utf-8 -*-
"""Automate Ruten fee payment and complete an SMS-based 3-D Secure challenge."""

from __future__ import annotations

__author__ = "blacktea"
__date__ = "2021/06/13"
__version__ = "1.0.0"

import configparser
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from otp_client import OTPRelayClient

SCRIPT_DIR = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = SCRIPT_DIR
    BUNDLE_DIR = SCRIPT_DIR

ROOT_URL = "https://www.ruten.com.tw/"
FEE_CENTER_URL = "https://point.ruten.com.tw/account/fee.php"
WAIT_TIMEOUT_SECONDS = 10
WAIT_POLL_SECONDS = 0.5

OTP_INPUT_SELECTORS: Tuple[Tuple[str, str], ...] = (
    (By.CSS_SELECTOR, "input[autocomplete='one-time-code']"),
    (By.CSS_SELECTOR, "input[inputmode='numeric'][maxlength='6']"),
    (By.CSS_SELECTOR, "input[name*='otp' i]"),
    (By.CSS_SELECTOR, "input[id*='otp' i]"),
    (By.CSS_SELECTOR, "input[name*='verify' i]"),
    (By.CSS_SELECTOR, "input[id*='verify' i]"),
    (By.CSS_SELECTOR, "input[name*='password' i][inputmode='numeric']"),
    (
        By.XPATH,
        "//input[not(@type='hidden') and "
        "(contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp') or "
        "contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp') or "
        "contains(@placeholder,'驗證碼') or contains(@aria-label,'驗證碼') or "
        "contains(@placeholder,'動態密碼') or contains(@aria-label,'動態密碼'))]",
    ),
)
OTP_SUBMIT_SELECTORS: Tuple[Tuple[str, str], ...] = (
    (By.CSS_SELECTOR, "button[id*='verify' i]"),
    (By.CSS_SELECTOR, "button[name*='verify' i]"),
    (By.CSS_SELECTOR, "button[id*='submit' i]"),
    (By.CSS_SELECTOR, "input[type='submit']"),
    (By.CSS_SELECTOR, "button[type='submit']"),
    (
        By.XPATH,
        "//button[contains(normalize-space(.),'驗證') or contains(normalize-space(.),'確認') "
        "or contains(normalize-space(.),'送出')]",
    ),
)
PAYMENT_SUCCESS_TEXT = ("付款成功", "繳費完成", "交易成功", "授權成功", "payment successful")
PAYMENT_FAILURE_TEXT = (
    "驗證碼錯誤",
    "驗證失敗",
    "交易失敗",
    "授權失敗",
    "交易已取消",
    "incorrect otp",
    "authentication failed",
    "transaction failed",
)

Locator = Tuple[str, str]


class PaymentFlowError(RuntimeError):
    pass


class Ruten:
    def __init__(self, driver: Optional[WebDriver] = None) -> None:
        self.config = configparser.ConfigParser(interpolation=None)
        self.config_path = self._resolve_runtime_file("config.ini")
        self.cookies_path = self._resolve_runtime_file("cookies.json")
        loaded = self.config.read(self.config_path, encoding="utf-8")
        if not loaded or not self.config.has_section("Ruten"):
            raise PaymentFlowError(f"找不到 Ruten 設定區塊: {self.config_path}")

        self.headless = self.config.getboolean("Ruten", "headless", fallback=False)
        self.background = self.config.getboolean("Ruten", "background", fallback=True)
        self.keep_browser_on_error = self.config.getboolean(
            "Ruten", "keep_browser_on_error", fallback=False
        )
        self.card_type = self.config.get("Ruten", "card_type", fallback="MASTER").upper()
        if not self.config.has_section(self.card_type):
            raise PaymentFlowError(f"找不到信用卡設定區塊: {self.card_type}")

        self.otp_server_url = os.environ.get(
            "OTP_SERVER_URL", self.config.get("OTP", "server_url", fallback="")
        ).strip()
        self.otp_consumer_token = os.environ.get(
            "OTP_CONSUMER_TOKEN", self.config.get("OTP", "consumer_token", fallback="")
        )
        self.otp_wait_seconds = self.config.getint("OTP", "wait_seconds", fallback=180)
        self.otp_page_wait_seconds = self.config.getint("OTP", "page_wait_seconds", fallback=90)
        self.otp_result_wait_seconds = self.config.getint("OTP", "result_wait_seconds", fallback=90)

        self._owns_driver = driver is None
        if driver is None:
            self._cleanup_linux_processes()
            self.driver = self._build_driver()
        else:
            self.driver = driver

    @staticmethod
    def _resolve_runtime_file(filename: str) -> Path:
        app_path = APP_DIR / filename
        if app_path.exists():
            return app_path
        bundled_path = BUNDLE_DIR / filename
        if bundled_path.exists():
            return bundled_path
        return app_path

    @staticmethod
    def _detect_chrome_major_version() -> Optional[int]:
        chrome_path = uc.find_chrome_executable()
        if not chrome_path:
            return None
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"(Get-Item '{chrome_path}').VersionInfo.ProductVersion",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                match = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout)
                if match:
                    return int(match.group(1))
            except Exception as exc:
                print(f"[WARN] 無法從 Chrome 檔案資訊取得版本: {exc}")
        try:
            result = subprocess.run(
                [chrome_path, "--version"], capture_output=True, text=True, check=True
            )
            match = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout)
            return int(match.group(1)) if match else None
        except Exception as exc:
            print(f"[WARN] 無法取得 Chrome 版本，改用 uc 自動偵測: {exc}")
            return None

    @staticmethod
    def _cleanup_linux_processes() -> None:
        if platform.system() == "Linux":
            subprocess.run(["pkill", "chrome"], check=False, capture_output=True)
            subprocess.run(["pkill", "-f", "webdriver"], check=False, capture_output=True)

    def _build_driver(self) -> WebDriver:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--no-sandbox")
        if self.headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--window-size=1200,600")
        elif self.background:
            chrome_options.add_argument("--start-minimized")

        major = self._detect_chrome_major_version()
        print(f"[INFO] 啟動 Chrome 中... headless={self.headless}, background={self.background}")
        driver = uc.Chrome(options=chrome_options, version_main=major) if major else uc.Chrome(options=chrome_options)
        if self.background and not self.headless:
            try:
                driver.minimize_window()
            except Exception as exc:
                print(f"[WARN] 無法最小化 Chrome 視窗: {exc}")
        return driver

    def quit_driver(self) -> None:
        try:
            self.driver.quit()
        except Exception as exc:
            print(f"[WARN] 關閉瀏覽器失敗: {exc}")

    def _wait(self, locator: Locator) -> Any:
        return WebDriverWait(self.driver, WAIT_TIMEOUT_SECONDS, WAIT_POLL_SECONDS).until(
            EC.presence_of_element_located(locator)
        )

    def _click(self, locator: Locator) -> None:
        WebDriverWait(self.driver, WAIT_TIMEOUT_SECONDS, WAIT_POLL_SECONDS).until(
            EC.element_to_be_clickable(locator)
        ).click()

    def _send_keys(self, locator: Locator, value: str) -> None:
        element = self._wait(locator)
        element.clear()
        element.send_keys(value)

    def _select_by_value(self, locator: Locator, value: str) -> None:
        Select(self._wait(locator)).select_by_value(value)

    def _select_by_value_with_diagnostics(self, locator: Locator, value: str, label: str) -> None:
        try:
            self._select_by_value(locator, value)
        except Exception as exc:
            try:
                options = [option.get_attribute("value") for option in Select(self._wait(locator)).options]
            except Exception:
                options = []
            raise PaymentFlowError(
                f"無法選擇{label}={value}；可用選項={options}"
            ) from exc

    @staticmethod
    def _to_webdriver_cookie(cookie: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            key: cookie[key]
            for key in ("name", "value", "path", "domain", "secure", "httpOnly")
            if key in cookie
        }
        if not cookie.get("session") and "expirationDate" in cookie:
            result["expiry"] = int(cookie["expirationDate"])
        same_site = cookie.get("sameSite")
        same_site_map = {"no_restriction": "None", "lax": "Lax", "strict": "Strict"}
        if same_site in same_site_map:
            result["sameSite"] = same_site_map[same_site]
        elif same_site in {"Strict", "Lax", "None"}:
            result["sameSite"] = same_site
        return result

    @staticmethod
    def _to_cdp_cookie(cookie: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            key: cookie[key]
            for key in ("name", "value", "path", "domain", "secure", "httpOnly")
            if key in cookie
        }
        if not cookie.get("session") and "expirationDate" in cookie:
            result["expires"] = float(cookie["expirationDate"])
        same_site = cookie.get("sameSite")
        same_site_map = {"no_restriction": "None", "lax": "Lax", "strict": "Strict"}
        if same_site in same_site_map:
            result["sameSite"] = same_site_map[same_site]
        elif same_site in {"Strict", "Lax", "None"}:
            result["sameSite"] = same_site
        return result

    def _load_cookies(self) -> Iterable[Dict[str, Any]]:
        with self.cookies_path.open(encoding="utf-8") as cookie_file:
            return json.load(cookie_file)

    def _restore_session_from_cookies(self) -> None:
        cookies = list(self._load_cookies())
        if not cookies:
            raise PaymentFlowError("cookies.json 沒有可用的 cookie")
        self.driver.get(ROOT_URL)
        restored = 0
        try:
            self.driver.execute_cdp_cmd("Network.enable", {})
            for cookie in cookies:
                if self.driver.execute_cdp_cmd("Network.setCookie", self._to_cdp_cookie(cookie)).get("success"):
                    restored += 1
        except Exception as exc:
            print(f"[WARN] CDP 載入 cookie 失敗，改用 Selenium add_cookie: {exc}")
            restored = 0
            for cookie in cookies:
                try:
                    self.driver.add_cookie(self._to_webdriver_cookie(cookie))
                    restored += 1
                except Exception as cookie_exc:
                    print(f"[WARN] 無法加入 cookie {cookie.get('name')}: {cookie_exc}")
        print(f"[INFO] 已載入 {restored}/{len(cookies)} 筆 cookie")

    def _cookie_login_snapshot(self) -> str:
        names = {cookie.get("name") for cookie in self.driver.get_cookies()}
        return f"login_cookie={'login' in names}, bid_member_cookie={'bid_member' in names}"

    def go_to_fee_center(self) -> None:
        self.driver.get(FEE_CENTER_URL)

    def _first_displayed(self, selectors: Tuple[Locator, ...]) -> Optional[Any]:
        for by, value in selectors:
            try:
                for element in self.driver.find_elements(by, value):
                    if element.is_displayed() and element.is_enabled():
                        return element
            except (NoSuchElementException, StaleElementReferenceException, WebDriverException):
                continue
        return None

    def _find_otp_in_frames(self, depth: int = 0) -> Optional[Any]:
        element = self._first_displayed(OTP_INPUT_SELECTORS)
        if element is not None:
            return element
        if depth >= 4:
            return None
        try:
            frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        except WebDriverException:
            return None
        for frame in frames:
            try:
                self.driver.switch_to.frame(frame)
                element = self._find_otp_in_frames(depth + 1)
                if element is not None:
                    return element
                self.driver.switch_to.parent_frame()
            except (StaleElementReferenceException, WebDriverException):
                try:
                    self.driver.switch_to.default_content()
                except WebDriverException:
                    pass
        return None

    def find_otp_input(self) -> Optional[Any]:
        """Find a challenge input across new windows and nested frames.

        On success Selenium remains focused on the window/frame containing the input.
        """
        try:
            current = self.driver.current_window_handle
            handles: List[str] = list(self.driver.window_handles)
        except WebDriverException:
            return None
        ordered_handles = [current] + [handle for handle in handles if handle != current]
        for handle in ordered_handles:
            try:
                self.driver.switch_to.window(handle)
                self.driver.switch_to.default_content()
                element = self._find_otp_in_frames()
                if element is not None:
                    return element
            except WebDriverException:
                continue
        return None

    def _page_has_text(self, candidates: Tuple[str, ...]) -> bool:
        try:
            source = self.driver.page_source.lower()
        except WebDriverException:
            return False
        return any(candidate.lower() in source for candidate in candidates)

    def _wait_for_otp_input_or_frictionless_success(self) -> Optional[Any]:
        deadline = time.monotonic() + self.otp_page_wait_seconds
        while time.monotonic() < deadline:
            element = self.find_otp_input()
            if element is not None:
                return element
            if self._page_has_text(PAYMENT_FAILURE_TEXT):
                raise PaymentFlowError("付款頁顯示交易或驗證失敗")
            if self._page_has_text(PAYMENT_SUCCESS_TEXT):
                return None
            time.sleep(1)
        raise PaymentFlowError("逾時：找不到 3DS 驗證碼欄位，也未偵測到付款成功頁")

    def _submit_otp(self, otp_input: Any, code: str) -> None:
        otp_input.clear()
        otp_input.send_keys(code)
        submit = self._first_displayed(OTP_SUBMIT_SELECTORS)
        if submit is not None:
            submit.click()
        else:
            otp_input.send_keys(Keys.ENTER)

    def _wait_for_3ds_result(self, challenge_url: str) -> None:
        deadline = time.monotonic() + self.otp_result_wait_seconds
        input_missing_since: Optional[float] = None
        while time.monotonic() < deadline:
            if self._page_has_text(PAYMENT_FAILURE_TEXT):
                raise PaymentFlowError("銀行拒絕 3DS 驗證或付款交易")
            if self._page_has_text(PAYMENT_SUCCESS_TEXT):
                print("[INFO] 已偵測到付款成功頁")
                return

            otp_input = self.find_otp_input()
            if otp_input is None:
                input_missing_since = input_missing_since or time.monotonic()
                try:
                    url_changed = self.driver.current_url != challenge_url
                except WebDriverException:
                    url_changed = True
                if url_changed and time.monotonic() - input_missing_since >= 3:
                    print("[INFO] 3DS 頁已完成並導回付款網站")
                    return
            else:
                input_missing_since = None
            time.sleep(1)
        raise PaymentFlowError("3DS 驗證送出後未能確認成功或導回付款網站")

    def complete_3ds(
        self,
        not_before: float,
        client: Optional[OTPRelayClient] = None,
    ) -> None:
        otp_input = self._wait_for_otp_input_or_frictionless_success()
        if otp_input is None:
            print("[INFO] 此交易未要求 OTP，已由銀行直接授權")
            return
        if not self.otp_server_url or not self.otp_consumer_token:
            raise PaymentFlowError(
                "付款需要 OTP，但未設定 OTP_SERVER_URL/OTP_CONSUMER_TOKEN 或 [OTP] 設定"
            )

        challenge_url = self.driver.current_url
        print("[INFO] 已找到 3DS 驗證頁，等待手機轉送的新簡訊")
        if client is None:
            client = OTPRelayClient(self.otp_server_url, self.otp_consumer_token)
        code = client.wait_for_code(not_before=not_before, timeout_seconds=self.otp_wait_seconds)
        print("[INFO] 已取得一次性驗證碼，準備送出（驗證碼不會寫入日誌）")
        self._submit_otp(otp_input, code)
        self._wait_for_3ds_result(challenge_url)

    def payfee(self) -> str:
        credit_card_button = (By.XPATH, '//button[@id="pay_credit_card"]')
        try:
            self._click(credit_card_button)
        except TimeoutException:
            print("[INFO] 目前沒有費用需要繳交")
            return "no_fee"

        self._click((By.XPATH, '//input[@id="accept"]'))
        fields = (
            ('//input[@id="crd_rocid"]', self.config["Ruten"]["userid"]),
            ('//input[@id="crd_by"]', self.config["Ruten"]["birth_year"]),
            ('//input[@id="crd_bm"]', self.config["Ruten"]["birth_month"]),
            ('//input[@id="crd_bd"]', self.config["Ruten"]["birth_day"]),
            ('//input[@id="crd_n1"]', self.config[self.card_type]["card_n1"]),
            ('//input[@id="crd_n2"]', self.config[self.card_type]["card_n2"]),
            ('//input[@id="crd_n3"]', self.config[self.card_type]["card_n3"]),
            ('//input[@id="crd_n4"]', self.config[self.card_type]["card_n4"]),
            ('//input[@id="crd_l3"]', self.config[self.card_type]["card_safe"]),
            ('//input[@id="zipcode"]', self.config["Ruten"]["zipcode"]),
            ('//input[@id="zipcode_accurate"]', self.config["Ruten"]["zipcode_accurate"]),
        )
        for xpath, value in fields:
            self._send_keys((By.XPATH, xpath), value)

        self._select_by_value_with_diagnostics(
            (By.XPATH, '//select[@id="crd_dlm"]'),
            self.config[self.card_type]["card_dlm"],
            "信用卡到期月份",
        )
        self._select_by_value_with_diagnostics(
            (By.XPATH, '//select[@id="crd_dly"]'),
            self.config[self.card_type]["card_dly"],
            "信用卡到期年份",
        )
        self._select_by_value((By.XPATH, '//select[@id="city"]'), self.config["Ruten"]["city"])
        self._select_by_value(
            (By.XPATH, '//select[@id="district"]'), self.config["Ruten"]["district"]
        )
        self._click((By.XPATH, '//input[@data-option="personal"]'))

        if not self.otp_server_url or not self.otp_consumer_token:
            raise PaymentFlowError(
                "付款前必須設定 OTP_SERVER_URL/OTP_CONSUMER_TOKEN 或 [OTP] 設定"
            )
        otp_client = OTPRelayClient(self.otp_server_url, self.otp_consumer_token)
        # Use relay time rather than the browser/phone clocks. If relay is down,
        # abort before clicking the irreversible payment submit button.
        not_before = otp_client.get_server_time()
        self._click((By.XPATH, '//button[@class="rt-button rt-button-submit rt-button-large"]'))
        self.complete_3ds(not_before, client=otp_client)
        return "paid"

    def main(self) -> str:
        self.driver.set_window_size(1200, 600)
        print(f"[INFO] config 路徑: {self.config_path}")
        print(f"[INFO] cookies 路徑: {self.cookies_path}")
        self._restore_session_from_cookies()
        print(f"[INFO] cookie 狀態: {self._cookie_login_snapshot()}")
        self.go_to_fee_center()
        print(f"[INFO] 目前頁面: {self.driver.current_url}")
        result = self.payfee()
        print(f"[INFO] 繳費流程結束: {result}")
        return result


def run() -> int:
    ruten: Optional[Ruten] = None
    failed = False
    try:
        ruten = Ruten()
        ruten.main()
        return 0
    except Exception as exc:
        failed = True
        print(f"[ERROR] 繳費流程失敗: {exc}", file=sys.stderr)
        return 1
    finally:
        if ruten is not None and not (failed and ruten.keep_browser_on_error):
            ruten.quit_driver()


if __name__ == "__main__":
    raise SystemExit(run())
