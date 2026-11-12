"""Build a clean, portable Windows package from this checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/public"))
    parser.add_argument("--work", type=Path, default=Path("build/public"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    output = args.output.resolve()
    work = args.work.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("TCL_LIBRARY", None)
    env.pop("TK_LIBRARY", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYINSTALLER_CONFIG_DIR"] = str(work / "cache")

    subprocess.run([sys.executable, str(source / "build_manager.py"), "--output", str(output),
                    "--work", str(work / "hub")], check=True, cwd=source, env=env)
    files = [output / "AI-Instance-Hub.exe"]
    files.extend((source / "LICENSE", source / "PUBLIC-START.md"))
    if not all(path.is_file() for path in files):
        raise RuntimeError("A required release file is missing")
    checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    manifest = {"release": "instance-hub-1.4.0", "portable": True,
                "bundled_account_data": False, "files": checksums}
    package = output / "instance-hub-1.4.0-windows.zip"
    temporary = package.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.name)
        archive.writestr("release-manifest.json", json.dumps(manifest, indent=2))
    temporary.replace(package)
    (output / "release-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"package": str(package), "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                      "files": checksums}, indent=2))


if __name__ == "__main__":
    main()
