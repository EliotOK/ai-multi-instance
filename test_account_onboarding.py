"""Focused tests for safe Codex account creation and official-client login."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine
from account_display import DisplayStore
from manager_backend import ManagerService


class CodexOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profiles = self.root / "CodexProfiles"
        self.old_app = engine.current_app()
        self.project_patch = patch.object(engine, "PROJECT_DIR", self.root)
        self.project_patch.start()
        self.addCleanup(self.project_patch.stop)
        self.addCleanup(engine.set_app, self.old_app, persist=False)
        self.display = DisplayStore(self.root / "account-display.json")
        self.service = ManagerService(self.display)
        self.exe = self.root / "ChatGPT.exe"

    def test_allocates_next_never_used_account_and_saves_display(self):
        self.profiles.mkdir()
        (self.profiles / "account-2").mkdir()
        (self.profiles / "account-3").mkdir()
        with patch.object(engine, "find_app_exe", return_value=self.exe) as find, \
             patch.object(engine, "launch_profile") as launch, \
             patch.object(engine, "launch_default_slot", side_effect=AssertionError("main slot touched")):
            name, message = self.service.create_codex_account("工作账号", "项目用")
        self.assertEqual(name, "account-4")
        self.assertTrue((self.profiles / name).is_dir())
        self.assertIn("浏览器登录", message)
        self.assertNotIn("已完成登录", message)
        self.assertEqual(self.display.for_app("codex")["profile:" + name],
                         {"label": "工作账号", "description": "项目用"})
        find.assert_called_once_with(refresh=True, app=engine.CODEX)
        launch.assert_called_once_with(name, exe=self.exe)

    def test_missing_codex_install_fails_before_creating_profile(self):
        with patch.object(engine, "find_app_exe", return_value=None), \
             patch.object(engine, "launch_profile") as launch:
            with self.assertRaisesRegex(RuntimeError, "Codex 未安装"):
                self.service.create_codex_account("工作账号", "")
        self.assertFalse(self.profiles.exists())
        launch.assert_not_called()

    def test_launch_failure_keeps_profile_and_login_retries_it(self):
        with patch.object(engine, "find_app_exe", return_value=self.exe), \
             patch.object(engine, "launch_profile", side_effect=[RuntimeError("spawn failed"), None]) as launch:
            name, message = self.service.create_codex_account("备用账号", "")
            profile = self.profiles / name
            self.assertTrue(profile.is_dir())
            self.assertIn("启动失败", message)
            self.assertIn("登录账号", message)
            retry_message = self.service.login_codex_profile(name)
        self.assertTrue(profile.is_dir())
        self.assertIn("官方客户端", retry_message)
        self.assertEqual([call.args for call in launch.call_args_list],
                         [(name,), (name,)])
        self.assertEqual(launch.call_args_list[1].kwargs, {"exe": self.exe})
        self.assertEqual(json.loads((self.root / "account-display.json").read_text("utf-8"))
                         ["accounts"]["codex"]["profile:" + name]["label"], "备用账号")

    def test_invalid_display_is_rejected_before_install_lookup(self):
        with patch.object(engine, "find_app_exe") as find:
            with self.assertRaises(ValueError):
                self.service.create_codex_account("  ", "")
        find.assert_not_called()


if __name__ == "__main__":
    unittest.main()
