# -*- coding: utf-8 -*-

__author__ = "blacktea"
__date__ = "2021/06/13"
__version__ = "0.0.1"

import configparser
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

SCRIPT_DIR = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = SCRIPT_DIR
    BUNDLE_DIR = SCRIPT_DIR

LOGIN_URL = "https://member.ruten.com.tw/user/login.htm"
ROOT_URL = "https://www.ruten.com.tw/"
FEE_CENTER_URL = "https://point.ruten.com.tw/account/fee.php"
WAIT_TIMEOUT_SECONDS = 10
WAIT_POLL_SECONDS = 0.5
POST_SUBMIT_WAIT_SECONDS = 60 * 5
FORCED_CARD_TYPE = "MASTER"

Locator = Tuple[str, str]


class Ruten:
    def __init__(self) -> None:
        self.config = configparser.ConfigParser()
        self.config_path = self._resolve_runtime_file("config.ini")
        self.cookies_path = self._resolve_runtime_file("cookies.json")
        self.config.read(self.config_path, encoding="utf-8")
        if not self.config.has_section("Ruten"):
            print(f"[WARN] 找不到 Ruten 設定區塊: {self.config_path}")

        self.headless = self.config.getboolean("Ruten", "headless", fallback=False)
        self.background = self.config.getboolean("Ruten", "background", fallback=True)
        self.card_type = FORCED_CARD_TYPE

        self._cleanup_linux_processes()
        self.driver = self._build_driver()

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
        """自動讀取本機 Chrome 主版本，避免 driver 版本被寫死。"""
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
                version_text = f"{result.stdout} {result.stderr}".strip()
            except Exception as exc:
                print(f"[WARN] 無法從 Chrome 檔案資訊取得版本，改用指令偵測: {exc}")
            else:
                match = re.search(r"(\d+)\.\d+\.\d+\.\d+", version_text)
                if match:
                    return int(match.group(1))
                print(f"[WARN] 無法解析 Chrome 檔案版本字串，改用指令偵測: {version_text}")

        try:
            result = subprocess.run(
                [chrome_path, "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
        except Exception as exc:
            print(f"[WARN] 無法取得 Chrome 版本，改用 uc 自動偵測: {exc}")
            return None

        version_text = f"{result.stdout} {result.stderr}".strip()
        match = re.search(r"(\d+)\.\d+\.\d+\.\d+", version_text)
        if not match:
            print(f"[WARN] 無法解析 Chrome 版本字串，改用 uc 自動偵測: {version_text}")
            return None
        return int(match.group(1))

    @staticmethod
    def _cleanup_linux_processes() -> None:
        if platform.system() != "Linux":
            return

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

        chrome_major_version = self._detect_chrome_major_version()
        print(
            f"[INFO] 啟動 Chrome 中... headless={self.headless}, "
            f"background={self.background}"
        )
        if chrome_major_version:
            print(f"[INFO] 偵測到 Chrome 主版本: {chrome_major_version}")
            driver = uc.Chrome(
                options=chrome_options,
                version_main=chrome_major_version,
            )
        else:
            driver = uc.Chrome(options=chrome_options)

        print("[INFO] Chrome 啟動完成")
        if self.background and not self.headless:
            try:
                driver.minimize_window()
            except Exception as exc:
                print(f"[WARN] 無法最小化 Chrome 視窗: {exc}")
        return driver

    def quit_driver(self) -> None:
        """關閉瀏覽器。"""
        self.driver.quit()

    def _wait(self, locator: Locator) -> Any:
        return WebDriverWait(
            self.driver,
            WAIT_TIMEOUT_SECONDS,
            WAIT_POLL_SECONDS,
        ).until(EC.presence_of_element_located(locator))

    def _click(self, locator: Locator) -> None:
        WebDriverWait(
            self.driver,
            WAIT_TIMEOUT_SECONDS,
            WAIT_POLL_SECONDS,
        ).until(EC.element_to_be_clickable(locator)).click()

    def _send_keys(self, locator: Locator, value: str) -> None:
        self._wait(locator).send_keys(value)

    def _select_by_value(self, locator: Locator, value: str) -> None:
        select = Select(self._wait(locator))
        select.select_by_value(value)

    def _select_by_value_or_pause(self, locator: Locator, value: str, label: str) -> None:
        try:
            self._select_by_value(locator, value)
        except Exception as exc:
            print(f"選擇{label}時發生錯誤: {exc}")
            print(f"嘗試的值: {value}")
            try:
                available_options = [
                    option.get_attribute("value")
                    for option in Select(self._wait(locator)).options
                ]
                print(f"可用的{label}選項: {available_options}")
            except Exception:
                print("無法獲取可用選項")
            print("請手動選擇正確的值，瀏覽器將保持開啟狀態")
            input("按 Enter 繼續...")

    @staticmethod
    def _to_webdriver_cookie(cookie: Dict[str, Any]) -> Dict[str, Any]:
        webdriver_cookie = {
            key: cookie[key]
            for key in ("name", "value", "path", "domain", "secure", "httpOnly")
            if key in cookie
        }

        if not cookie.get("session") and "expirationDate" in cookie:
            webdriver_cookie["expiry"] = int(cookie["expirationDate"])

        same_site = cookie.get("sameSite")
        if same_site == "no_restriction":
            webdriver_cookie["sameSite"] = "None"
        elif same_site == "lax":
            webdriver_cookie["sameSite"] = "Lax"
        elif same_site == "strict":
            webdriver_cookie["sameSite"] = "Strict"
        elif same_site in {"Strict", "Lax", "None"}:
            webdriver_cookie["sameSite"] = same_site

        return webdriver_cookie

    @staticmethod
    def _to_cdp_cookie(cookie: Dict[str, Any]) -> Dict[str, Any]:
        cdp_cookie = {
            key: cookie[key]
            for key in ("name", "value", "path", "domain", "secure", "httpOnly")
            if key in cookie
        }

        if not cookie.get("session") and "expirationDate" in cookie:
            cdp_cookie["expires"] = float(cookie["expirationDate"])

        same_site = cookie.get("sameSite")
        if same_site == "no_restriction":
            cdp_cookie["sameSite"] = "None"
        elif same_site == "lax":
            cdp_cookie["sameSite"] = "Lax"
        elif same_site == "strict":
            cdp_cookie["sameSite"] = "Strict"
        elif same_site in {"Strict", "Lax", "None"}:
            cdp_cookie["sameSite"] = same_site

        return cdp_cookie

    def _load_cookies(self) -> Iterable[Dict[str, Any]]:
        with self.cookies_path.open(encoding="utf-8") as cookie_file:
            return json.load(cookie_file)

    def _restore_session_from_cookies(self) -> None:
        cookies = list(self._load_cookies())
        if not cookies:
            print("[WARN] cookies.json 沒有可用的 cookie")
            return

        self.driver.get(ROOT_URL)
        restored_count = 0
        failed_cookie_names = []

        try:
            self.driver.execute_cdp_cmd("Network.enable", {})
            for cookie in cookies:
                cdp_cookie = self._to_cdp_cookie(cookie)
                result = self.driver.execute_cdp_cmd("Network.setCookie", cdp_cookie)
                if result.get("success"):
                    restored_count += 1
                else:
                    failed_cookie_names.append(cookie.get("name", "<unknown>"))
        except Exception as exc:
            print(f"[WARN] CDP 載入 cookie 失敗，改用 Selenium add_cookie: {exc}")
            restored_count = 0
            failed_cookie_names = []
            for cookie in cookies:
                try:
                    self.driver.add_cookie(self._to_webdriver_cookie(cookie))
                    restored_count += 1
                except Exception as cookie_exc:
                    failed_cookie_names.append(cookie.get("name", "<unknown>"))
                    print(f"[WARN] 無法加入 cookie {cookie.get('name')}: {cookie_exc}")

        print(f"[INFO] 已載入 {restored_count}/{len(cookies)} 筆 cookie")
        if failed_cookie_names:
            print(f"[WARN] 載入失敗的 cookie: {', '.join(failed_cookie_names)}")

    def _cookie_login_snapshot(self) -> str:
        cookie_map = {
            cookie["name"]: cookie["value"]
            for cookie in self.driver.get_cookies()
            if "name" in cookie and "value" in cookie
        }
        login_value = cookie_map.get("login", "<missing>")
        has_bid_member = "bid_member" in cookie_map
        return f"login={login_value}, bid_member={has_bid_member}"

    def close_ad(self) -> None:
        """關閉露天廣告。"""
        try:
            self._click((By.XPATH, '//button[@class="rt-lightbox-close-button"]'))
        except Exception as exc:
            print(f"close_ad error: {exc}")

    def go_to_fee_center(self) -> None:
        """前往計費中心。"""
        try:
            time.sleep(1)
            self.driver.get(FEE_CENTER_URL)
            self.card_type = FORCED_CARD_TYPE
        except Exception as exc:
            print(f"go_to_fee_center error: {exc}")

    def payfee(self) -> None:
        """繳費。"""
        credit_card_button = (By.XPATH, '//button[@id="pay_credit_card"]')
        fill_user_data = (By.XPATH, '//input[@id="accept"]')

        field_values = [
            ((By.XPATH, '//input[@id="crd_rocid"]'), self.config["Ruten"]["userid"]),
            ((By.XPATH, '//input[@id="crd_by"]'), self.config["Ruten"]["birth_year"]),
            ((By.XPATH, '//input[@id="crd_bm"]'), self.config["Ruten"]["birth_month"]),
            ((By.XPATH, '//input[@id="crd_bd"]'), self.config["Ruten"]["birth_day"]),
            ((By.XPATH, '//input[@id="crd_n1"]'), self.config[self.card_type]["card_n1"]),
            ((By.XPATH, '//input[@id="crd_n2"]'), self.config[self.card_type]["card_n2"]),
            ((By.XPATH, '//input[@id="crd_n3"]'), self.config[self.card_type]["card_n3"]),
            ((By.XPATH, '//input[@id="crd_n4"]'), self.config[self.card_type]["card_n4"]),
            ((By.XPATH, '//input[@id="crd_l3"]'), self.config[self.card_type]["card_safe"]),
            ((By.XPATH, '//input[@id="zipcode"]'), self.config["Ruten"]["zipcode"]),
            (
                (By.XPATH, '//input[@id="zipcode_accurate"]'),
                self.config["Ruten"]["zipcode_accurate"],
            ),
        ]
        invoice_type = (By.XPATH, '//input[@data-option="personal"]')
        pay_button = (By.XPATH, '//button[@class="rt-button rt-button-submit rt-button-large"]')

        try:
            self._click(credit_card_button)
        except TimeoutException:
            print("[INFO] 目前沒有費用需要繳交")
            return

        try:
            time.sleep(1)
            self._click(fill_user_data)

            for locator, value in field_values:
                self._send_keys(locator, value)

            self._select_by_value_or_pause(
                (By.XPATH, '//select[@id="crd_dlm"]'),
                self.config[self.card_type]["card_dlm"],
                "信用卡到期月份",
            )
            self._select_by_value_or_pause(
                (By.XPATH, '//select[@id="crd_dly"]'),
                self.config[self.card_type]["card_dly"],
                "信用卡到期年份",
            )
            self._select_by_value((By.XPATH, '//select[@id="city"]'), self.config["Ruten"]["city"])
            self._select_by_value(
                (By.XPATH, '//select[@id="district"]'),
                self.config["Ruten"]["district"],
            )

            self._click(invoice_type)
            time.sleep(1)
            self._click(pay_button)
            time.sleep(POST_SUBMIT_WAIT_SECONDS)
        except Exception as exc:
            print(f"payfee error: {exc}")
            print("發生錯誤，但瀏覽器將保持開啟狀態以供調試")
            print("請檢查網頁上的表單元素是否正確")

    def main(self) -> None:
        self.driver.set_window_size(1200, 600)
        print(f"[INFO] config 路徑: {self.config_path}")
        print(f"[INFO] cookies 路徑: {self.cookies_path}")
        print("[INFO] 開始載入露天首頁並還原 cookies")
        self._restore_session_from_cookies()
        print(f"[INFO] cookie 狀態: {self._cookie_login_snapshot()}")

        print("[INFO] 準備進入計費中心")
        self.go_to_fee_center()
        print(f"[INFO] 目前頁面: {self.driver.current_url}")
        print("[INFO] 準備執行繳費流程")
        self.payfee()


if __name__ == "__main__":
    ruten = Ruten()
    ruten.main()
