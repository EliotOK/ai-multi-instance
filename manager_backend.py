"""Serialized account operations used by the unified desktop manager."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import engine
from account_display import DisplayStore


@dataclass(frozen=True)
class Account:
    name: str | None
    running: bool | None
    pids: tuple[int, ...] = ()
    display_name: str | None = None
    description: str | None = None

    @property
    def key(self) -> str:
        return "main" if self.name is None else "profile:" + self.name

    @property
    def label(self) -> str:
        return self.display_name if self.display_name is not None else "主账号" if self.name is None else "第二账号" if self.name == "account-2" else "账号 " + self.name

    @property
    def detail(self) -> str:
        return self.description if self.description is not None else "默认登录 · 本机" if self.name is None else "独立登录 · " + self.name


@dataclass(frozen=True)
class Snapshot:
    app_key: str
    accounts: tuple[Account, ...]
    error: str | None = None


class ManagerService:
    def __init__(self, display_store=None):
        # engine's app selection is global. Never let a refresh switch apps
        # midway through a start/stop operation.
        self.lock = threading.RLock()
        self.display_store = display_store or DisplayStore()

    def _select(self, app_key: str):
        app = engine.APPS.get(app_key)
        if app is None:
            raise ValueError("未知应用")
        engine.set_app(app, persist=False)
        return app

    def snapshot(self, app_key: str) -> Snapshot:
        with self.lock:
            app = self._select(app_key)
            names = [p.name for p in engine.list_profiles()]
            display = self.display_store.for_app(app_key)
            def account(name, running, pids=()):
                value=display.get("main" if name is None else "profile:"+name,{})
                return Account(name,running,tuple(pids),value.get("label"),value.get("description"))
            try:
                rows = engine._processes(app.exe_name, strict=True)
                profiles = engine._profiles_from_processes(rows)
                main = engine._default_slot_pids_from_processes(rows)
            except RuntimeError:
                return Snapshot(app_key, tuple(account(name, None) for name in [None, *names]),
                                "无法读取运行状态。请通过桌面启动入口运行，或点击刷新重试。")
            accounts = [account(None, bool(main), main)]
            accounts.extend(account(name, bool(profiles.get(name)), profiles.get(name, [])) for name in names)
            return Snapshot(app_key, tuple(accounts))

    def save_display(self, app_key, name, label, description):
        with self.lock:
            self._select(app_key)
            if name is not None and (name not in {p.name for p in engine.list_profiles()} or not engine.valid_profile_name(name)):
                raise ValueError("账号目录不存在，请刷新列表")
            values=self.display_store.save(app_key,"main" if name is None else "profile:"+name,label,description)
            return values

    def maintain_appearance(self, snapshot):
        if snapshot.app_key != "codex" or snapshot.error:
            return
        with self.lock:
            self._select("codex")
            selected=next((a for a in snapshot.accounts if a.name=="account-2"),None)
            if selected and selected.running:
                engine.ensure_profile_icon("account-2")

    def perform(self, app_key: str, name: str | None, action: str) -> str:
        if action not in ("open", "close", "restart"):
            raise ValueError("未知操作")
        with self.lock:
            app = self._select(app_key)
            if name is not None:
                if name in ("", ".", "..") or not engine.valid_profile_name(name):
                    raise ValueError("账号名称无效")
                if name not in {p.name for p in engine.list_profiles()}:
                    raise ValueError("账号目录不存在，请刷新列表")
            # Fail before acting if process ownership cannot be verified.
            snapshot = self.snapshot(app_key)
            if snapshot.error:
                raise RuntimeError(snapshot.error)
            selected = next(a for a in snapshot.accounts if a.name == name)
            label = app.display + " · " + selected.label
            if action == "close":
                if name is None:
                    engine.close_default_slot(wait=15, strict=True)
                else:
                    engine.close_profile(name, wait=15, strict=True)
                return label + " 已退出"
            exe = engine.find_app_exe(refresh=True, app=app)
            if exe is None:
                raise RuntimeError(app.display + " 未安装，或无法找到桌面应用")
            engine.validate_launch(name)
            if action == "restart":
                if name is None:
                    engine.close_default_slot(wait=15, strict=True)
                    engine.launch_default_slot(exe=exe)
                else:
                    engine.restart_profile(name, exe=exe)
                return label + " 已重新启动"
            if name is None:
                engine.launch_default_slot(exe=exe)
            else:
                engine.launch_profile(name, exe=exe)
            return label + (" 正在显示窗口" if selected.running else " 正在启动")
