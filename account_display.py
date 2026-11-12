"""Editable presentation only; immutable account identifiers stay separate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from app_paths import data_root


def validate_display(label: str, description: str) -> tuple[str, str]:
    if not isinstance(label, str) or not isinstance(description, str):
        raise ValueError("名称和描述必须是文字")
    label, description = label.strip(), description.strip()
    if not label or len(label) > 40:
        raise ValueError("名称请输入 1–40 个字")
    if len(description) > 120:
        raise ValueError("描述最多 120 个字")
    if any(ord(char) < 32 for char in label + description):
        raise ValueError("名称和描述请使用单行文字")
    return label, description


class DisplayStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else data_root() / "account-display.json"

    def read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "accounts": {}}
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("accounts"), dict):
                raise ValueError("unsupported display settings")
            return data
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"无法读取账号显示设置：{self.path}\n{exc}") from exc

    def for_app(self, app: str) -> dict:
        items = self.read()["accounts"].get(app, {})
        if not isinstance(items, dict):
            raise RuntimeError("账号显示设置格式错误")
        for key, item in items.items():
            if not isinstance(item, dict):
                raise RuntimeError("账号显示设置格式错误")
            validate_display(item.get("label"), item.get("description"))
        return items

    def save(self, app: str, key: str, label: str, description: str) -> tuple[str, str]:
        label, description = validate_display(label, description)
        original = self.path.read_bytes() if self.path.exists() else None
        data = self.read()
        data["accounts"].setdefault(app, {})[key] = {"label": label, "description": description}
        candidate = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="account-display-", suffix=".tmp", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            current = self.path.read_bytes() if self.path.exists() else None
            if current != original:
                raise RuntimeError("显示设置已被另一个窗口修改，请刷新后重试")
            temporary.replace(self.path)
            if self.path.read_bytes() != candidate:
                raise RuntimeError("显示设置保存验证失败")
        finally:
            temporary.unlink(missing_ok=True)
        return label, description
