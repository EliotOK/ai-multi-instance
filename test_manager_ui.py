"""Exercise this app's Tk and native shell components without desktop automation."""
import ctypes
import gc
import time
import tkinter as tk
import unittest
import uuid

from manager_backend import Account, Snapshot
from manager_ui import HubWindow
from windows_shell import CLASS_NAME, SHOW_MESSAGE, TRAY_MESSAGE, set_identity


class FakeService:
    def __init__(self):
        self.calls=[]
        self.edits={}
        self.names=[None,"account-2"]

    def snapshot(self, app):
        return Snapshot(app,tuple(Account(name,True,(),*self.edits.get(name,(None,None))) for name in self.names))

    def save_display(self,app,name,label,description):
        self.edits[name]=(label,description)
        return label,description

    def perform(self, app, name, action):
        self.calls.append((app,name,action))
        return "操作完成"

    def create_codex_account(self,label,description):
        name=f"account-{len(self.names)+1}"
        self.names.append(name)
        self.edits[name]=(label,description)
        return name,"已打开 Codex。请在官方客户端中完成浏览器登录。"

    def login_codex_profile(self,name):
        self.calls.append(("codex",name,"login"))
        return "已打开 Codex。请在官方客户端中完成浏览器登录。"


class ManagerUiTests(unittest.TestCase):
    def setUp(self):
        set_identity()
        self.root=tk.Tk()
        self.root.withdraw()
        self.service=FakeService()
        self.window=HubWindow(self.root,self.service,native=True,
                              shell_identity=uuid.uuid4().hex)
        self.window.render(self.service.snapshot("codex"))
        self.root.update_idletasks()

    def tearDown(self):
        self.window.close()
        self.window.worker.join(timeout=3)
        self.assertFalse(self.window.worker.is_alive())
        del self.window
        del self.root
        gc.collect()

    def pump(self, condition):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.02)
        self.fail("Native event did not reach the GUI")

    def test_independent_taskbar_and_tray_registration(self):
        native=self.window.shell
        data=native.diagnostics()
        self.assertTrue(data["tray_added"])
        self.assertTrue(data["taskbar_appwindow"])
        self.assertFalse(data["toolwindow"])
        self.assertEqual(data["owner"],0)
        self.assertNotEqual(native.class_name,CLASS_NAME)
        self.assertFalse(self.window.record_diagnostics)

    def test_close_to_tray_and_reopen_protocol(self):
        self.window.hide()
        self.assertEqual(self.root.state(),"withdrawn")
        self.window.shell.api.post(self.window.shell.hwnd,SHOW_MESSAGE,0,0)
        self.pump(lambda:self.root.state()=="normal")
        self.assertTrue(self.window.shell.added)

    def test_tray_click_callback_restores_window(self):
        self.window.hide()
        self.window.shell.api.post(self.window.shell.hwnd,TRAY_MESSAGE,0,0x202)
        self.pump(lambda:self.root.state()=="normal")

    def test_unknown_status_blocks_account_actions(self):
        self.window.render(Snapshot("codex",(Account(None,None),Account("account-2",None)),"状态未知"))
        self.window.act("close")
        self.assertFalse(self.window.busy)
        self.assertFalse(self.service.calls)
        self.assertFalse({r[-1] for r in self.window.regions}.intersection({"open","close","restart"}))

    def test_selected_account_action_reaches_only_selected_account(self):
        self.window.act("close")
        self.pump(lambda:bool(self.service.calls))
        self.assertEqual(self.service.calls,[("codex","account-2","close")])

    def test_action_buttons_fit_above_footer(self):
        self.root.update()
        self.window.draw()
        height=max(620,self.window.canvas.winfo_height()/self.window.scale)
        controls=[r for r in self.window.regions if r[-1] in {"open","close","restart"}]
        self.assertEqual(len(controls),3)
        self.assertTrue(all(r[3]<height-67 for r in controls))

    def test_onboarding_buttons_do_not_overlap_account_cards_or_footer(self):
        self.root.update()
        self.window.draw()
        regions={r[-1]:r for r in self.window.regions}
        self.assertLess(regions["create"][3],354)
        self.assertLess(regions["login"][3],self.window.canvas.winfo_height()/self.window.scale-67)

    def test_create_and_login_actions_route_to_codex_service(self):
        self.root.deiconify()
        self.root.update()
        self.window.create_account()
        self.window.create_name.set("新的工作账号")
        self.window.create_description.set("项目")
        self.window.submit_create_account()
        self.pump(lambda:not self.window.busy and self.window.create_dialog is None)
        self.pump(lambda:self.window.selected_key=="profile:account-3" and
                  "profile:account-3" in self.window.accounts)
        self.assertEqual(self.window.accounts["profile:account-3"].label,"新的工作账号")
        self.window.act("login")
        self.pump(lambda:self.service.calls and self.service.calls[-1][2]=="login")
        self.assertEqual(self.service.calls[-1],("codex","account-3","login"))

    def test_shutdown_removes_only_this_tests_tray_icon(self):
        native=self.window.shell
        self.window.close()
        self.assertFalse(native.added)
        self.assertIsNone(native.hwnd)

    def test_edit_both_accounts_updates_labels_without_process_actions(self):
        self.root.deiconify()
        self.root.update()
        for key,name,label,description in [("main",None,"日常账号","个人"),("profile:account-2","account-2","开发账号","项目")]:
            self.window.edit_account(key)
            self.window.editor_name.set(label)
            self.window.editor_description.set(description)
            self.window.save_editor()
            self.pump(lambda:self.window.editor is None and not self.window.busy)
            self.pump(lambda:self.window.accounts[key].label==label)
            self.assertEqual(self.window.accounts[key].detail,description)
            self.assertEqual(self.service.edits[name],(label,description))
        self.assertFalse(self.service.calls)

    def test_invalid_name_keeps_editor_open_and_cancel_discards_changes(self):
        self.root.deiconify()
        self.root.update()
        self.window.edit_account("main")
        self.window.editor_name.set(" ")
        self.window.save_editor()
        self.assertIn("1–40",self.window.editor_status.get())
        self.assertFalse(self.window.busy)
        self.window.close_editor()
        self.assertFalse(self.service.edits)
        self.assertEqual(self.window.accounts["main"].label,"主账号")


if __name__=="__main__":
    unittest.main()
