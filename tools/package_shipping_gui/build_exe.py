from __future__ import annotations

from contextlib import contextmanager
import subprocess
import sys
import os
import shutil
import tempfile
from pathlib import Path


APP_NAME = "package_shipping_gui"
ENTRYPOINT = Path("tools/package_shipping_gui/__main__.py")
HIDDEN_IMPORTS = [
    "googleapiclient.discovery",
    "googleapiclient.errors",
    "googleapiclient.http",
    "google_auth_oauthlib.flow",
    "google.auth.transport.requests",
    "google.oauth2.credentials",
]


def build_pyinstaller_command(python_executable: Path, project_root: Path) -> list[str]:
    command = [
        str(python_executable),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(project_root),
    ]
    for import_name in HIDDEN_IMPORTS:
        command.extend(["--hidden-import", import_name])
    command.append(str(project_root / ENTRYPOINT))
    return command


def prepare_tcl_runtime(project_root: Path, python_executable: Path) -> dict[str, str]:
    source = python_executable.resolve().parent / "tcl"
    if not source.exists():
        return {}

    runtime_root = project_root / "build" / "package_shipping_gui_tcl"
    shutil.copytree(source, runtime_root, dirs_exist_ok=True)
    return {
        "TCL_LIBRARY": str(runtime_root / "tcl8.6"),
        "TK_LIBRARY": str(runtime_root / "tk8.6"),
    }


@contextmanager
def preserve_local_state(project_root: Path):
    local_dir = project_root / "dist" / APP_NAME / ".local"
    if not local_dir.exists():
        yield
        return

    with tempfile.TemporaryDirectory(prefix=f"{APP_NAME}_local_") as temp_dir:
        backup_dir = Path(temp_dir) / ".local"
        shutil.copytree(local_dir, backup_dir)
        try:
            yield
        finally:
            if local_dir.exists():
                shutil.rmtree(local_dir)
            local_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup_dir, local_dir)


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    command = build_pyinstaller_command(Path(sys.executable), project_root)
    env = os.environ.copy()
    env.update(prepare_tcl_runtime(project_root, Path(sys.executable)))
    with preserve_local_state(project_root):
        subprocess.run(command, cwd=project_root, check=True, env=env)
    print(project_root / "dist" / APP_NAME / f"{APP_NAME}.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
