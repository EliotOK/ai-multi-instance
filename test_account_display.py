from pathlib import Path
import tempfile
import unittest
from unittest import mock

import engine
from account_display import DisplayStore
from manager_backend import ManagerService
from profile_branding import eligible_windows


class AccountDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"account-display.json"
        self.store=DisplayStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_names_and_descriptions_survive_reload_without_cross_account_overwrite(self):
        self.store.save("codex","main","日常账号","日常和笔记")
        self.store.save("claude","main","Claude","独立应用")
        self.store.save("codex","profile:account-2","开发账号","")
        reload=DisplayStore(self.path)
        self.assertEqual(reload.for_app("codex"),{"main":{"label":"日常账号","description":"日常和笔记"},"profile:account-2":{"label":"开发账号","description":""}})
        self.assertEqual(reload.for_app("claude")["main"]["label"],"Claude")

    def test_invalid_edit_preserves_valid_file(self):
        self.store.save("codex","main","主账号","默认描述")
        before=self.path.read_bytes()
        for label,description in [(" ",""),("长"*41,""),("有效","长"*121),("换\n行","")]:
            with self.assertRaises(ValueError):
                self.store.save("codex","main",label,description)
            self.assertEqual(self.path.read_bytes(),before)

    def test_corrupt_settings_are_not_overwritten(self):
        self.path.write_text('{"version":',encoding="utf-8")
        before=self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.store.save("codex","main","名字","")
        self.assertEqual(before,self.path.read_bytes())

    def test_rename_keeps_immutable_account_target(self):
        previous=engine.current_app()
        service=ManagerService(self.store)
        try:
            with mock.patch.object(engine,"list_profiles",return_value=[Path("account-2")]),mock.patch.object(engine,"_processes",return_value=[]),mock.patch.object(engine,"close_profile") as close,mock.patch.object(engine,"close_default_slot") as close_main:
                service.save_display("codex","account-2","主账号","我取的名字")
                service.perform("codex","account-2","close")
                close.assert_called_once_with("account-2",wait=15,strict=True)
                close_main.assert_not_called()
                accounts=service.snapshot("codex").accounts
                self.assertEqual(accounts[1].key,"profile:account-2")
                self.assertEqual(accounts[1].detail,"我取的名字")
        finally:
            engine.set_app(previous,persist=False)

    def test_icon_window_selection_excludes_main_and_unowned_windows(self):
        base={"hwnd":1,"pid":22,"class":"Chrome_WidgetWin_1","visible":True,"owner":0,"toolwindow":False}
        windows=[base,dict(base,hwnd=2,pid=11),dict(base,hwnd=3,owner=1),dict(base,hwnd=4,toolwindow=True),dict(base,hwnd=5,visible=False),dict(base,hwnd=6,**{"class":"Other"})]
        self.assertEqual(eligible_windows(windows,{22}),[base])


if __name__=="__main__":
    unittest.main()
