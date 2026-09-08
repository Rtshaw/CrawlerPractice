from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.package_shipping_gui.app import APP_DIR, main


def _smoke_test(create_tk: bool = False) -> int:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if create_tk:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
    return 0


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--tk-smoke-test" in argv:
        return _smoke_test(create_tk=True)
    if "--smoke-test" in argv:
        return _smoke_test()
    main()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
