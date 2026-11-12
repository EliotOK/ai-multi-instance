"""Separate bundled artwork from persistent account data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

RESOURCE_DIR = Path(__file__).resolve().parent


def resolve_data_root(bundle: Path, executable: Path, frozen: bool, override: str | None = None) -> Path:
    if override:
        target = Path(override).expanduser().resolve()
        if not target.is_dir():
            raise ValueError(f"账号数据目录不存在：{target}")
        return target
    if not frozen:
        return bundle
    adjacent = executable.resolve().parent
    settings = adjacent / "instance-hub.json"
    if settings.is_file():
        try:
            value = json.loads(settings.read_text("utf-8"))["data_root"]
            if not isinstance(value, str) or not value.strip():
                raise ValueError("data_root must be a nonempty path")
            target = Path(value).expanduser()
            if not target.is_absolute():
                target = adjacent / target
            if not target.is_dir():
                raise ValueError("directory does not exist")
            return target.resolve()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"无法读取账号目录设置：{settings} ({exc})") from exc
    defaults = bundle / "hub-defaults.json"
    if defaults.is_file():
        value = json.loads(defaults.read_text("utf-8")).get("data_root")
        if value and Path(value).is_dir():
            return Path(value).resolve()
    # A generic build stores profiles beside the EXE, never in _MEIPASS.
    return adjacent


def data_root() -> Path:
    return resolve_data_root(RESOURCE_DIR, Path(sys.executable), bool(getattr(sys, "frozen", False)),
                             os.environ.get("AI_INSTANCE_HUB_DATA_DIR"))
