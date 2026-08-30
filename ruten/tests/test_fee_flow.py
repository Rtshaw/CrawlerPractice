import configparser
import unittest
from decimal import Decimal
from unittest.mock import patch

from fee import PaymentFlowError, Ruten
from otp_client import OTPEvent


class FakeElement:
    def __init__(self, on_click=None, *, text="", attributes=None, selected=False):
        self.value = ""
        self.clicked = False
        self.on_click = on_click
        self.text = text
        self.attributes = dict(attributes or {})
        self.selected = selected

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def clear(self):
        self.value = ""

    def send_keys(self, value):
        self.value += str(value)

    def get_attribute(self, name):
        if name == "value" and name not in self.attributes:
            return self.value
        return self.attributes.get(name)

    def is_selected(self):
        return self.selected

    def click(self):
        self.clicked = True
        if self.attributes.get("type") == "radio":
            self.selected = True
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

    def find_element(self, by, value):
        if value == "body":
            return FakeElement(text=self.page_source)
        elements = self.find_elements(by, value)
        if len(elements) != 1:
            raise AssertionError(f"expected one element for {value}, got {len(elements)}")
        return elements[0]

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


class FakeEsunDriver:
    def __init__(self):
        self.stage = "method"
        self.current_url = "https://acs.esunbank.com.tw/3ds/challenge"
        self.body = FakeElement(text="交易金額 TWD 1,234")
        self.method = FakeElement(text="傳送OTP驗證密碼")
        self.next_button = FakeElement(on_click=self.show_entry, text="下一步")
        self.transaction = FakeElement(attributes={"value": "transaction-123"})
        self.challenge = FakeElement()
        self.radios = [
            FakeElement(attributes={"type": "radio", "value": "TEST"}),
            FakeElement(attributes={"type": "radio", "value": "ABCD"}),
        ]
        self.submit = FakeElement(on_click=self.finish)

    @property
    def page_source(self):
        return self.body.text

    def show_entry(self):
        self.stage = "entry"

    def finish(self):
        self.stage = "success"
        self.current_url = "https://point.ruten.com.tw/account/paybillok.php"
        self.body.text = "信用卡授權成功 您已經繳費成功"

    def find_elements(self, by, value):
        if value == "form#acs_challenge":
            return [] if self.stage == "success" else [FakeElement()]
        if value == "//*[normalize-space(.)='傳送OTP驗證密碼']":
            return [self.method] if self.stage == "method" else []
        if value == "//button[normalize-space(.)='下一步']":
            return [self.next_button] if self.stage == "method" else []
        if self.stage != "entry":
            return []
        if value == "#acsTransID":
            return [self.transaction]
        if value == "#challengeValue":
            return [self.challenge]
        if value == 'input[type="radio"][name="identifier"]':
            return self.radios
        if value == "button#btnSubmit[type=button]":
            return [self.submit]
        return []

    def find_element(self, by, value):
        if value == "body":
            return self.body
        elements = self.find_elements(by, value)
        if len(elements) != 1:
            raise AssertionError(f"expected one element for {value}, got {len(elements)}")
        return elements[0]


class FakeEsunOTPClient:
    def __init__(self, event):
        self.event = event
        self.calls = []

    def wait_for_event(self, *, not_before, timeout_seconds):
        self.calls.append((not_before, timeout_seconds))
        return self.event


class FakePaymentPageDriver:
    def __init__(self, events):
        self.events = events

    @property
    def current_url(self):
        self.events.append("wait_for_payment_form")
        return "https://point.ruten.com.tw/account/paymybill.php"


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

    def test_completes_esun_two_stage_challenge_with_matching_identifier(self):
        ruten = self.make_ruten()
        ruten.driver = FakeEsunDriver()
        client = FakeEsunOTPClient(
            OTPEvent(
                code="864209",
                identifier="TEST",
                amount=Decimal("1234"),
                sender="BANK",
                received_at=1700000000.25,
            )
        )

        ruten.complete_3ds(not_before=12345.0, client=client)

        self.assertTrue(ruten.driver.method.clicked)
        self.assertTrue(ruten.driver.next_button.clicked)
        self.assertTrue(ruten.driver.radios[0].is_selected())
        self.assertFalse(ruten.driver.radios[1].is_selected())
        self.assertEqual(ruten.driver.challenge.value, "864209")
        self.assertTrue(ruten.driver.submit.clicked)
        self.assertEqual(client.calls, [(12345.0, 30)])

    def test_stops_before_otp_submit_when_esun_amount_does_not_match(self):
        ruten = self.make_ruten()
        ruten.driver = FakeEsunDriver()
        client = FakeEsunOTPClient(
            OTPEvent(
                code="864209",
                identifier="TEST",
                amount=Decimal("999"),
                sender="BANK",
                received_at=1700000000.25,
            )
        )

        with self.assertRaises(PaymentFlowError):
            ruten.complete_3ds(not_before=12345.0, client=client)

        self.assertFalse(ruten.driver.submit.clicked)


class FeeFormFlowTests(unittest.TestCase):
    def make_ruten(self):
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
        ruten.events = []
        ruten.driver = FakePaymentPageDriver(ruten.events)
        ruten.not_before = None

        def record_click(locator):
            ruten.clicked.append(locator)
            ruten.events.append(locator[1])

        ruten._click = record_click
        ruten._send_keys = lambda locator, value: ruten.sent.append((locator, value))
        ruten._select_by_value = lambda locator, value: ruten.selected.append((locator, value))
        ruten._select_by_value_with_diagnostics = (
            lambda locator, value, label: ruten.selected.append((locator, value))
        )
        ruten.complete_3ds = (
            lambda not_before, client=None: setattr(ruten, "not_before", not_before)
        )
        return ruten

    @patch("fee.OTPRelayClient", FakeOTPClient)
    def test_payfee_uses_configured_card_and_invokes_3ds(self):
        ruten = self.make_ruten()
        self.assertEqual(ruten.payfee(), "paid")
        sent_values = [value for _, value in ruten.sent]
        self.assertIn("1111", sent_values)
        self.assertIn("4444", sent_values)
        self.assertEqual(ruten.not_before, 12000.0)

    @patch("fee.OTPRelayClient", FakeOTPClient)
    def test_payfee_leaves_readonly_zipcode_to_page(self):
        ruten = self.make_ruten()

        self.assertEqual(ruten.payfee(), "paid")

        sent_locators = [locator[1] for locator, _ in ruten.sent]
        self.assertNotIn('//input[@id="zipcode"]', sent_locators)
        self.assertIn('//input[@id="zipcode_accurate"]', sent_locators)

    @patch("fee.OTPRelayClient", FakeOTPClient)
    def test_payfee_waits_for_payment_form_before_accept(self):
        ruten = self.make_ruten()

        self.assertEqual(ruten.payfee(), "paid")

        accept = '//input[@id="accept"]'
        self.assertIn("wait_for_payment_form", ruten.events)
        self.assertLess(
            ruten.events.index("wait_for_payment_form"), ruten.events.index(accept)
        )


if __name__ == "__main__":
    unittest.main()
