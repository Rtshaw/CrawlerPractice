from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from .google_api import GoogleApiClient, GoogleApiUnavailable, spreadsheet_id_from_url
from .parser import parse_package_text
from .planner import UpdatePlan, build_update_plan


def _resolve_app_dir(
    frozen: bool | None = None,
    executable: Path | None = None,
    module_file: Path | None = None,
) -> Path:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        executable = executable or Path(sys.executable)
        return executable.resolve().parent
    module_file = module_file or Path(__file__)
    return module_file.resolve().parent


APP_DIR = _resolve_app_dir()
LOCAL_DIR = APP_DIR / ".local"
CONFIG_FILE = LOCAL_DIR / "config.json"
TOKEN_FILE = LOCAL_DIR / "token.json"
CREDENTIALS_FILE = LOCAL_DIR / "credentials.json"


@dataclass(frozen=True)
class PreviewRequest:
    package_text: str
    sheet_url: str
    amount: str
    allow_overwrite: bool


@dataclass(frozen=True)
class ApplyRequest:
    sheet_url: str
    plan: UpdatePlan


class PackageShippingApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("包裹運費寫入 Google Sheet")
        self.config = _load_config()
        self.plan = None
        self.client = GoogleApiClient(CREDENTIALS_FILE, TOKEN_FILE)
        self._build_ui()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        top = ttk.Frame(self.root, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Google Sheet URL").grid(row=0, column=0, sticky="w")
        self.sheet_url = tk.StringVar(value=self.config.get("spreadsheet_url", ""))
        ttk.Entry(top, textvariable=self.sheet_url).grid(row=0, column=1, sticky="ew", padx=6)

        ttk.Label(top, text="運費").grid(row=0, column=2, sticky="w")
        self.amount = tk.StringVar(value=self.config.get("amount", "58"))
        ttk.Entry(top, textvariable=self.amount, width=8).grid(row=0, column=3, sticky="w", padx=6)

        self.allow_overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="允許覆寫非空 H2", variable=self.allow_overwrite).grid(
            row=0, column=4, sticky="w"
        )

        text_frame = ttk.LabelFrame(self.root, text="待解析文本", padding=8)
        text_frame.grid(row=1, column=0, sticky="nsew", padx=8)
        text_frame.columnconfigure(0, weight=1)
        self.package_text = tk.Text(text_frame, height=10, wrap="word")
        self.package_text.grid(row=0, column=0, sticky="nsew")

        result_frame = ttk.LabelFrame(self.root, text="預覽結果", padding=8)
        result_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        columns = (
            "tracking",
            "store",
            "qty",
            "order",
            "sheet",
            "current_h2",
            "new_h2",
            "status",
        )
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=12)
        headings = {
            "tracking": "運單號",
            "store": "店別",
            "qty": "數量",
            "order": "訂單號",
            "sheet": "工作表",
            "current_h2": "目前 H2",
            "new_h2": "寫入",
            "status": "狀態",
        }
        for col, text in headings.items():
            self.tree.heading(col, text=text)
            self.tree.column(col, width=120 if col != "sheet" else 180, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        buttons = ttk.Frame(self.root, padding=8)
        buttons.grid(row=3, column=0, sticky="ew")
        ttk.Button(buttons, text="解析預覽", command=self.preview).pack(side="left")
        ttk.Button(buttons, text="寫入 H2", command=self.apply).pack(side="left", padx=6)
        ttk.Button(buttons, text="儲存設定", command=self.save_settings).pack(side="left")
        self.status = tk.StringVar(value="等待輸入")
        ttk.Label(buttons, textvariable=self.status).pack(side="right")

    def preview(self) -> None:
        request = PreviewRequest(
            package_text=self.package_text.get("1.0", "end"),
            sheet_url=self.sheet_url.get().strip(),
            amount=self.amount.get().strip(),
            allow_overwrite=self.allow_overwrite.get(),
        )
        self._run_background(self._preview_worker, request)

    def apply(self) -> None:
        if self.plan is None:
            messagebox.showwarning("尚未預覽", "請先按解析預覽。")
            return
        if self.plan.has_blockers:
            messagebox.showerror("不能寫入", "預覽結果仍有 blocked 項目，請先處理。")
            return
        if not messagebox.askyesno("確認寫入", f"要將 {len(self.plan.ready_rows)} 張工作表 H2 寫入 {self.plan.amount} 嗎？"):
            return
        request = ApplyRequest(sheet_url=self.sheet_url.get().strip(), plan=self.plan)
        self._run_background(self._apply_worker, request)

    def save_settings(self) -> None:
        _save_config({"spreadsheet_url": self.sheet_url.get().strip(), "amount": self.amount.get().strip()})
        self.status.set("設定已儲存")

    def _preview_worker(self, request: PreviewRequest) -> None:
        text = request.package_text
        if request.amount:
            text = text.rstrip() + f"\n${request.amount}\n"
        batch = parse_package_text(text)
        spreadsheet_id = spreadsheet_id_from_url(request.sheet_url)
        self.client.connect()
        orders = {
            item.tracking_number: self.client.find_order_numbers(item.tracking_number)
            for item in batch.items
        }
        tabs = self.client.list_sheet_tabs_with_h2(spreadsheet_id)
        self.plan = build_update_plan(
            batch,
            order_numbers_by_tracking=orders,
            sheet_tabs=tabs,
            allow_overwrite=request.allow_overwrite,
        )
        self.root.after(0, self._render_plan)

    def _apply_worker(self, request: ApplyRequest) -> None:
        spreadsheet_id = spreadsheet_id_from_url(request.sheet_url)
        sheet_ids = [row.sheet_id for row in request.plan.ready_rows if row.sheet_id is not None]
        self.client.write_h2_values(spreadsheet_id, sheet_ids, request.plan.amount)
        self.root.after(0, lambda: self.status.set("寫入完成，請再按解析預覽驗證讀回。"))

    def _render_plan(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.plan.rows:
            self.tree.insert(
                "",
                "end",
                values=(
                    row.tracking_number,
                    row.store_code,
                    row.quantity,
                    row.order_number or "",
                    row.sheet_title or "",
                    row.current_h2 or "",
                    row.new_h2,
                    f"{row.status}: {row.message}",
                ),
            )
        self.status.set(f"預覽完成：{len(self.plan.ready_rows)} ready / {len(self.plan.rows)} total")

    def _run_background(self, target, *args) -> None:
        self.status.set("執行中...")

        def runner():
            try:
                target(*args)
            except (GoogleApiUnavailable, ValueError, RuntimeError) as exc:
                self.root.after(0, lambda error=exc: self._show_error(error))
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._show_error(error))

        threading.Thread(target=runner, daemon=True).start()

    def _show_error(self, exc: Exception) -> None:
        self.status.set("失敗")
        messagebox.showerror("錯誤", str(exc))


def main() -> None:
    root = tk.Tk()
    root.geometry("1200x720")
    PackageShippingApp(root)
    root.mainloop()


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _save_config(config: dict) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
