"""Reproducible single-file launcher build; account data is never bundled."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--work", type=Path, default=Path("build/instance-hub"))
    parser.add_argument("--data-root", type=Path, help="Reconnect this build to an existing account directory")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    defaults = work / "hub-defaults.json"
    defaults.write_text(json.dumps({"data_root": str(args.data_root.resolve()) if args.data_root else None}), encoding="utf-8")
    files = ["assets/instance-hub.ico", "assets/instance-hub.png",
             "assets/codex-account-2.ico", "assets/codex-account-2.png",
             "assets/fonts/Baloo2-ExtraBold.ttf", "assets/fonts/InstanceHubRounded-Bold.otf",
             "assets/fonts/OFL.txt", "assets/fonts/GenSen-OFL.txt", "assets/fonts/README.txt"]
    command = [sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--noupx", "--noconfirm",
               "--name", "AI-Instance-Hub", "--icon", str(source / "assets/instance-hub.ico"),
               "--version-file", str(source / "assets/launcher-version.txt"),
               "--distpath", str(args.output.resolve()), "--workpath", str(work / "pyinstaller"),
               "--specpath", str(work), "--add-data", str(defaults) + ":."]
    # Conda keeps Tcl/Tk DLLs under Library/bin, outside the directory scanned
    # for _tkinter.pyd dependencies. A missing DLL makes a frozen GUI stall at
    # Windows' loader dialog before our smoke-test report can be written.
    conda_bin = Path(sys.base_prefix) / "Library" / "bin"
    for name in ("tcl86t.dll", "tk86t.dll"):
        dll = conda_bin / name
        if dll.is_file():
            command.extend(("--add-binary", str(dll) + ":."))
    for name in files:
        path = source / name
        if not path.is_file():
            raise FileNotFoundError(path)
        command.extend(("--add-data", str(path) + ":" + path.parent.relative_to(source).as_posix()))
    command.append(str(source / "manager.pyw"))
    env = dict(os.environ)
    env.pop("TCL_LIBRARY", None)
    env.pop("TK_LIBRARY", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYINSTALLER_CONFIG_DIR"] = str(work / "cache")
    subprocess.run(command, check=True, cwd=source, env=env)


if __name__ == "__main__":
    main()
