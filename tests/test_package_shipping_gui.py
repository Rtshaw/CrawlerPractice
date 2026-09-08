import subprocess
import sys
import tempfile
import threading
import unittest
from importlib import util
from pathlib import Path

from tools.package_shipping_gui import app
from tools.package_shipping_gui.google_api import GoogleApiClient
from tools.package_shipping_gui.parser import (
    extract_order_numbers,
    parse_package_text,
)
from tools.package_shipping_gui.planner import (
    SheetTab,
    build_update_plan,
)


PACKAGE_TEXT = """
包裹 #179760001691 M × 3
包裹 #929415286833 raku × 1
包裹 #A225863095695A T × 3

3+1+3=7
$58
"""


class PackageShippingParserTests(unittest.TestCase):
    def test_parse_package_text_extracts_shipments_and_amount(self):
        batch = parse_package_text(PACKAGE_TEXT)

        self.assertEqual(batch.amount, 58)
        self.assertEqual(batch.total_quantity, 7)
        self.assertEqual([item.tracking_number for item in batch.items], [
            "179760001691",
            "929415286833",
            "A225863095695A",
        ])
        self.assertEqual([item.store_code for item in batch.items], ["M", "raku", "T"])
        self.assertEqual([item.quantity for item in batch.items], [3, 1, 3])

    def test_parse_package_text_rejects_wrong_total(self):
        with self.assertRaisesRegex(ValueError, "quantity total"):
            parse_package_text("包裹 #111 M × 2\n1+1+1=3\n$58")

    def test_extract_order_numbers_supports_known_store_emails(self):
        samples = {
            "melon": "ご注文番号\n122513470\n送り状番号\n179760001691",
            "rakuten": "・注文番号：213310-20260807-0521346913\n・お届け伝票番号：929415286833",
            "gamers": "ご注文番号\n24039067\n送り状番号\n988806423345",
            "toranoana": "出荷番号：20260820-001660\nお問い合わせ番号 225863095695",
            "mangaoh": "【受注番号】mgo-00383252\nお問い合せ番号 352396419970",
        }

        self.assertEqual(extract_order_numbers(samples["melon"]), ["122513470"])
        self.assertEqual(extract_order_numbers(samples["rakuten"]), ["0521346913"])
        self.assertEqual(extract_order_numbers(samples["gamers"]), ["24039067"])
        self.assertEqual(extract_order_numbers(samples["toranoana"]), ["001660"])
        self.assertEqual(extract_order_numbers(samples["mangaoh"]), ["00383252"])


class PackageShippingPlannerTests(unittest.TestCase):
    def test_build_update_plan_matches_order_number_to_sheet_title(self):
        batch = parse_package_text(PACKAGE_TEXT)
        order_numbers_by_tracking = {
            "179760001691": ["122513470"],
            "929415286833": ["0521346913"],
            "A225863095695A": ["001660"],
        }
        sheet_tabs = [
            SheetTab(sheet_id=1, title="0729 122513470", current_h2=""),
            SheetTab(sheet_id=2, title="0807 0521346913", current_h2="71"),
            SheetTab(sheet_id=3, title="0822 001660", current_h2=""),
        ]

        plan = build_update_plan(
            batch,
            order_numbers_by_tracking=order_numbers_by_tracking,
            sheet_tabs=sheet_tabs,
            allow_overwrite=False,
        )

        self.assertEqual([row.sheet_title for row in plan.rows], [
            "0729 122513470",
            "0807 0521346913",
            "0822 001660",
        ])
        self.assertEqual([row.status for row in plan.rows], ["ready", "blocked", "ready"])
        self.assertIn("H2 is not empty", plan.rows[1].message)

    def test_build_update_plan_fails_closed_on_ambiguous_orders(self):
        batch = parse_package_text("包裹 #179760001691 M × 3\n3=3\n$58")

        plan = build_update_plan(
            batch,
            order_numbers_by_tracking={"179760001691": ["122513470", "122587945"]},
            sheet_tabs=[SheetTab(sheet_id=1, title="0729 122513470", current_h2="")],
            allow_overwrite=True,
        )

        self.assertEqual(plan.rows[0].status, "blocked")
        self.assertIn("multiple order numbers", plan.rows[0].message)


class PackageShippingGoogleApiTests(unittest.TestCase):
    def test_list_sheet_tabs_with_h2_uses_one_batch_read(self):
        class Request:
            def __init__(self, response):
                self.response = response

            def execute(self):
                return self.response

        class ValuesService:
            def __init__(self):
                self.batch_get_calls = []

            def batchGet(self, **kwargs):
                self.batch_get_calls.append(kwargs)
                return Request(
                    {
                        "valueRanges": [
                            {"values": [["69"]]},
                            {},
                            {"values": [["71"]]},
                        ]
                    }
                )

        class SpreadsheetsService:
            def __init__(self):
                self.values_service = ValuesService()

            def get(self, **_kwargs):
                return Request(
                    {
                        "sheets": [
                            {"properties": {"sheetId": 1, "title": "0814 00383252"}},
                            {"properties": {"sheetId": 2, "title": "O'Brien"}},
                            {"properties": {"sheetId": 3, "title": "0822 001660"}},
                        ]
                    }
                )

            def values(self):
                return self.values_service

        class SheetsService:
            def __init__(self):
                self.spreadsheets_service = SpreadsheetsService()

            def spreadsheets(self):
                return self.spreadsheets_service

        service = SheetsService()
        client = GoogleApiClient(Path("credentials.json"), Path("token.json"))
        client.sheets = service

        tabs = client.list_sheet_tabs_with_h2("spreadsheet-id")

        self.assertEqual([tab.current_h2 for tab in tabs], ["69", "", "71"])
        self.assertEqual(len(service.spreadsheets_service.values_service.batch_get_calls), 1)
        self.assertEqual(
            service.spreadsheets_service.values_service.batch_get_calls[0]["ranges"],
            ["'0814 00383252'!H2", "'O''Brien'!H2", "'0822 001660'!H2"],
        )


class PackageShippingAppPathTests(unittest.TestCase):
    def test_preview_captures_tk_values_before_background_worker(self):
        class Value:
            def __init__(self, value):
                self.value = value

            def get(self, *args):
                return self.value

        instance = app.PackageShippingApp.__new__(app.PackageShippingApp)
        instance.package_text = Value("包裹 #111 M x 1")
        instance.sheet_url = Value("https://docs.google.com/spreadsheets/d/sheet-id/edit")
        instance.amount = Value("69")
        instance.allow_overwrite = Value(False)
        captured = []
        instance._run_background = lambda target, *args: captured.append((target, args))

        instance.preview()

        self.assertEqual(len(captured), 1)
        request = captured[0][1][0]
        self.assertEqual(request.package_text, "包裹 #111 M x 1")
        self.assertEqual(request.sheet_url, "https://docs.google.com/spreadsheets/d/sheet-id/edit")
        self.assertEqual(request.amount, "69")
        self.assertFalse(request.allow_overwrite)

    def test_background_error_callback_keeps_exception_after_worker_finishes(self):
        class Root:
            def __init__(self):
                self.callbacks = []
                self.callback_ready = threading.Event()

            def after(self, _delay, callback):
                self.callbacks.append(callback)
                self.callback_ready.set()

        class Status:
            def set(self, _value):
                pass

        root = Root()
        instance = app.PackageShippingApp.__new__(app.PackageShippingApp)
        instance.root = root
        instance.status = Status()
        errors = []
        instance._show_error = errors.append

        instance._run_background(lambda: (_ for _ in ()).throw(OSError("expected failure")))

        self.assertTrue(root.callback_ready.wait(1))
        root.callbacks[0]()
        self.assertEqual([str(error) for error in errors], ["expected failure"])

    def test_resolve_app_dir_uses_exe_directory_when_frozen(self):
        self.assertTrue(hasattr(app, "_resolve_app_dir"))

        resolved = app._resolve_app_dir(
            frozen=True,
            executable=Path(r"C:\Tools\package_shipping_gui.exe"),
            module_file=Path(r"D:\Project\SideProject\CrawlerPractice\tools\package_shipping_gui\app.py"),
        )

        self.assertEqual(resolved, Path(r"C:\Tools"))


class PackageShippingBuildTests(unittest.TestCase):
    def test_build_module_exposes_onedir_pyinstaller_command(self):
        spec = util.find_spec("tools.package_shipping_gui.build_exe")

        self.assertIsNotNone(spec)

        from tools.package_shipping_gui.build_exe import build_pyinstaller_command

        command = build_pyinstaller_command(Path(r"C:\Python311\python.exe"), Path.cwd())

        self.assertIn("-m", command)
        self.assertIn("PyInstaller", command)
        self.assertIn("--onedir", command)
        self.assertNotIn("--onefile", command)
        self.assertIn("--windowed", command)
        self.assertIn("--name", command)
        self.assertIn("package_shipping_gui", command)
        self.assertIn("--hidden-import", command)
        self.assertIn("googleapiclient.discovery", command)

    def test_prepare_tcl_runtime_copies_tcl_tree_for_pyinstaller(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_home = root / "python"
            source_tcl = python_home / "tcl"
            (source_tcl / "tcl8.6").mkdir(parents=True)
            (source_tcl / "tk8.6").mkdir(parents=True)
            (source_tcl / "tcl8.6" / "init.tcl").write_text("init", encoding="utf-8")
            project_root = root / "project"
            project_root.mkdir()

            from tools.package_shipping_gui.build_exe import prepare_tcl_runtime

            env = prepare_tcl_runtime(project_root, python_home / "python.exe")

            runtime_root = project_root / "build" / "package_shipping_gui_tcl"
            self.assertEqual(env["TCL_LIBRARY"], str(runtime_root / "tcl8.6"))
            self.assertEqual(env["TK_LIBRARY"], str(runtime_root / "tk8.6"))
            self.assertEqual((runtime_root / "tcl8.6" / "init.tcl").read_text(encoding="utf-8"), "init")

    def test_preserve_local_state_restores_credentials_after_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_dir = root / "dist" / "package_shipping_gui" / ".local"
            local_dir.mkdir(parents=True)
            (local_dir / "credentials.json").write_text("credentials", encoding="utf-8")
            (local_dir / "token.json").write_text("token", encoding="utf-8")

            from tools.package_shipping_gui.build_exe import preserve_local_state

            with preserve_local_state(root):
                for path in local_dir.iterdir():
                    path.unlink()
                (local_dir / "build-only.txt").write_text("temporary", encoding="utf-8")

            self.assertEqual((local_dir / "credentials.json").read_text(encoding="utf-8"), "credentials")
            self.assertEqual((local_dir / "token.json").read_text(encoding="utf-8"), "token")
            self.assertFalse((local_dir / "build-only.txt").exists())

    def test_launcher_supports_smoke_test_without_opening_gui(self):
        from tools.package_shipping_gui import __main__ as launcher

        self.assertTrue(hasattr(launcher, "_smoke_test"))
        self.assertEqual(launcher.run(["--smoke-test"]), 0)

    def test_launcher_supports_script_mode_smoke_test(self):
        result = subprocess.run(
            [
                sys.executable,
                str(Path("tools/package_shipping_gui/__main__.py")),
                "--smoke-test",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
