"""GUI / single-file EXE entry point for the unified account launcher."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import tkinter as tk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", choices=("codex", "claude"), default="codex")
    parser.add_argument("--data-dir", help="Existing multi-instance account root")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--shell-test", action="store_true")
    parser.add_argument("--test-report", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--decorate-profile")
    parser.add_argument("--open-account")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["AI_INSTANCE_HUB_DATA_DIR"] = args.data_dir
    import engine
    engine.set_app(engine.APPS[args.app],persist=False)
    if args.decorate_profile:
        from profile_branding import run_worker
        run_worker(args.decorate_profile)
        return
    from app_paths import data_root
    from manager_backend import Account, ManagerService, Snapshot
    from manager_ui import HubWindow
    from windows_shell import SingleInstance, set_identity, SHOW_MESSAGE, TRAY_MESSAGE
    import engine

    if args.open_account:
        ManagerService().perform(args.app,args.open_account,"open")
        return

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    set_identity()
    guard = SingleInstance()
    testing = args.smoke_test or args.shell_test
    if not testing and not guard.acquire():
        guard.close()
        return
    try:
        root = tk.Tk()
        if testing:
            root.withdraw()

            class PreviewService:
                def __init__(self):
                    self.calls = []
                    self.edits = {}

                def snapshot(self, key):
                    return Snapshot(key, tuple(Account(name,True,(),*self.edits.get(name,(None,None))) for name in (None,"account-2")))

                def perform(self, app, name, action):
                    self.calls.append((app, name, action))
                    return "操作完成"

                def save_display(self,app,name,label,description):
                    self.edits[name]=(label,description)
                    return label,description

            service = PreviewService()
            window = HubWindow(root, service, args.app, native=args.shell_test,
                               shell_identity="cli-" + str(os.getpid()) if args.shell_test else None)

            def pump(condition):
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    root.update()
                    if condition():
                        return
                    time.sleep(.02)
                raise AssertionError("GUI event timed out")

            try:
                window.render(service.snapshot(args.app))
                root.update_idletasks()
                assert len(window.accounts) == 2 and window.selected().name == "account-2"
                report = {"passed": False, "frozen": bool(getattr(sys, "frozen", False)),
                          "data_root": str(data_root()), "theme": "warm-paper",
                          "fonts": {"display": window.fonts.display, "rounded": window.fonts.rounded}}
                assert window.fonts.display == "Baloo 2" and window.fonts.rounded == "Instance Hub Rounded"
                if args.shell_test:
                    data = window.shell.diagnostics()
                    assert data["tray_added"] and data["taskbar_appwindow"] and not data["toolwindow"] and data["owner"] == 0
                    report["shell"] = data
                    window.hide()
                    assert root.state() == "withdrawn"
                    window.shell.api.post(window.shell.hwnd, SHOW_MESSAGE, 0, 0)
                    pump(lambda: root.state() == "normal")
                    window.hide()
                    window.shell.api.post(window.shell.hwnd, TRAY_MESSAGE, 0, 0x202)
                    pump(lambda: root.state() == "normal")
                    report["hide_restore"] = True
                window.act("close")
                pump(lambda: bool(service.calls) and not window.busy)
                assert service.calls == [(args.app, "account-2", "close")]
                report["isolated_account_routing"] = True
                window.render(Snapshot(args.app, (Account(None, None), Account("account-2", None))))
                window.act("close")
                assert not window.busy and len(service.calls) == 1
                assert not {r[-1] for r in window.regions}.intersection({"open", "restart", "close"})
                report["unknown_state_blocked"] = True
                window.edit_account("main")
                window.editor_name.set("工作账号")
                window.editor_description.set("项目与开发")
                window.save_editor()
                pump(lambda:window.editor is None and not window.busy)
                pump(lambda:window.accounts["main"].label=="工作账号")
                assert window.accounts["main"].detail=="项目与开发"
                report["editable_name_description"] = True
                window.selected_key="profile:account-2"
                window.render(Snapshot(args.app, (Account(None, True), Account("account-2", False))))
                assert any(r[-1] == "open" for r in window.regions)
                assert not any(r[-1] == "close" for r in window.regions)
                # Inspect real profiles read-only; all test actions use the fake service.
                snapshot = ManagerService().snapshot(args.app)
                report["live_accounts"] = [{"name": a.name, "running": a.running} for a in snapshot.accounts]
                report["live_scan_error"] = snapshot.error
                for account in snapshot.accounts:
                    engine.validate_launch(account.name)
                report["configs_valid"] = True
                if args.preview:
                    from preview_render import capture_window
                    window.last_message="选择账号，打开或管理它的窗口。"
                    window.render(snapshot if not snapshot.error else service.snapshot(args.app))
                    root.deiconify()
                    root.update()
                    capture_window(root, args.preview)
                    report["preview"] = str(args.preview.resolve())
                window.close()
                assert not window.shell or not window.shell.added
                report["tray_cleanup"] = True
                report["passed"] = True
                if args.test_report:
                    args.test_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                if sys.stdout:
                    print(json.dumps(report, ensure_ascii=False))
            finally:
                window.close()
        else:
            HubWindow(root, app_key=args.app)
            root.mainloop()
    finally:
        guard.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if "--test-report" in sys.argv:
            try:
                path = Path(sys.argv[sys.argv.index("--test-report") + 1])
                path.write_text(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            except (OSError, IndexError):
                pass
        if getattr(sys, "frozen", False) and "--test-report" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "启动器未能打开", 0x10)
        elif not getattr(sys, "frozen", False):
            raise
        sys.exit(1)
