import configparser
import unittest
from unittest.mock import patch

from fee import Ruten


class FakeElement:
    def __init__(self, on_click=None):
        self.value = ""
        self.clicked = False
        self.on_click = on_click

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def clear(self):
        self.value = ""

    def send_keys(self, value):
        self.value += str(value)

    def click(self):
        self.clicked = True
        if self.on_click:
            self.on_click()


class SwitchTo:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.current_window_handle = handle
        self.default_content()

    def default_content(self):
        self.driver.stack = []
        self.driver.node = self.driver.windows[self.driver.current_window_handle]

    def frame(self, frame):
        self.driver.stack.append(self.driver.node)
        self.driver.node = frame

    def parent_frame(self):
        self.driver.node = self.driver.stack.pop()


class FakeChallengeDriver:
    def __init__(self):
        self.otp = FakeElement()
        self.submit = FakeElement(on_click=self.finish)
        nested = {"frames": [], "otp": self.otp, "submit": self.submit}
        outer = {"frames": [nested]}
        self.windows = {
            "main": {"frames": []},
            "challenge": {"frames": [outer]},
        }
        self.current_window_handle = "main"
        self.window_handles = ["main", "challenge"]
        self.node = self.windows["main"]
        self.stack = []
        self.switch_to = SwitchTo(self)
        self.current_url = "https://bank.example/3ds"
        self.page_source = "3-D Secure"

    def find_elements(self, by, value):
        if value == "iframe,frame":
            return self.node.get("frames", [])
        if value == "input[autocomplete='one-time-code']" and "otp" in self.node:
            return [self.node["otp"]]
        if value == "button[id*='verify' i]" and "submit" in self.node:
            return [self.node["submit"]]
        return []

    def finish(self):
        self.current_url = "https://point.ruten.com.tw/payment/result"
        self.page_source = "付款成功"
        self.windows["challenge"] = {"frames": []}
        self.node = self.windows["challenge"]
        self.stack = []


class FakeOTPClient:
    calls = []

    def __init__(self, server_url, token):
        self.server_url = server_url
        self.token = token

    def get_server_time(self):
        return 12000.0

    def wait_for_code(self, *, not_before, timeout_seconds):
        self.calls.append((self.server_url, self.token, not_before, timeout_seconds))
        return "864209"


class FeeThreeDSTests(unittest.TestCase):
    def make_ruten(self):
        ruten = Ruten.__new__(Ruten)
        ruten.driver = FakeChallengeDriver()
        ruten.otp_server_url = "https://otp.example.com"
        ruten.otp_consumer_token = "consumer-token"
        ruten.otp_wait_seconds = 30
        ruten.otp_page_wait_seconds = 1
        ruten.otp_result_wait_seconds = 1
        return ruten

    def test_finds_nested_otp_in_second_window(self):
        ruten = self.make_ruten()
        self.assertIs(ruten.find_otp_input(), ruten.driver.otp)
        self.assertEqual(ruten.driver.current_window_handle, "challenge")
        self.assertEqual(len(ruten.driver.stack), 2)

    @patch("fee.OTPRelayClient", FakeOTPClient)
    def test_completes_3ds_without_logging_or_reusing_old_code(self):
        FakeOTPClient.calls.clear()
        ruten = self.make_ruten()
        ruten.complete_3ds(not_before=12345.0)
        self.assertEqual(ruten.driver.otp.value, "864209")
        self.assertTrue(ruten.driver.submit.clicked)
        self.assertEqual(FakeOTPClient.calls[0][2], 12345.0)


class FeeFormFlowTests(unittest.TestCase):
    @patch("fee.OTPRelayClient", FakeOTPClient)
    def test_payfee_uses_configured_card_and_invokes_3ds(self):
        ruten = Ruten.__new__(Ruten)
        config = configparser.ConfigParser()
        config.read_dict(
            {
                "Ruten": {
                    "userid": "ID",
                    "birth_year": "80",
                    "birth_month": "1",
                    "birth_day": "2",
                    "city": "City",
                    "district": "District",
                    "zipcode": "100",
                    "zipcode_accurate": "1",
                },
                "JCB": {
                    "card_n1": "1111",
                    "card_n2": "2222",
                    "card_n3": "3333",
                    "card_n4": "4444",
                    "card_safe": "999",
                    "card_dlm": "12",
                    "card_dly": "2030",
                },
            }
        )
        ruten.config = config
        ruten.card_type = "JCB"
        ruten.otp_server_url = "https://otp.example.com"
        ruten.otp_consumer_token = "consumer-token"
        ruten.sent = []
        ruten.clicked = []
        ruten.selected = []
        ruten.not_before = None
        ruten._click = lambda locator: ruten.clicked.append(locator)
        ruten._send_keys = lambda locator, value: ruten.sent.append((locator, value))
        ruten._select_by_value = lambda locator, value: ruten.selected.append((locator, value))
        ruten._select_by_value_with_diagnostics = (
            lambda locator, value, label: ruten.selected.append((locator, value))
        )
        ruten.complete_3ds = (
            lambda not_before, client=None: setattr(ruten, "not_before", not_before)
        )

        self.assertEqual(ruten.payfee(), "paid")
        sent_values = [value for _, value in ruten.sent]
        self.assertIn("1111", sent_values)
        self.assertIn("4444", sent_values)
        self.assertEqual(ruten.not_before, 12000.0)


if __name__ == "__main__":
    unittest.main()
