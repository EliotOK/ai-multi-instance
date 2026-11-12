"""An invalid config must never tear down the currently working account."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import engine
from manager_backend import ManagerService


class LaunchPreflightTests(unittest.TestCase):
    def setUp(self):
        self.previous = engine.current_app()
        engine.set_app(engine.CODEX, persist=False)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = mock.patch.object(engine, "PROFILES_DIR", self.root)
        self.patch.start()
        self.cfg = self.root / "account-2" / ".codex" / "config.toml"
        self.cfg.parent.mkdir(parents=True)
        self.exe = Path(r"C:\Program Files\WindowsApps\OpenAI.Codex_1_x64__2p2nqsd0c76g0\app\ChatGPT.exe")

    def tearDown(self):
        self.patch.stop()
        engine.set_app(self.previous, persist=False)
        self.temp.cleanup()

    def test_quoted_and_unquoted_duplicate_notify_preserves_process(self):
        text = '"notify" = ["old"]\nnotify = ["new"]\n'
        self.cfg.write_text(text, encoding="utf-8")
        with mock.patch.object(engine, "close_profile") as stop, mock.patch.object(engine, "launch_profile") as launch:
            with self.assertRaisesRegex(RuntimeError, "配置检查未通过"):
                engine.restart_profile("account-2", exe=self.exe)
            stop.assert_not_called()
            launch.assert_not_called()
        self.assertEqual(self.cfg.read_text("utf-8"), text)

    def test_bad_launch_settings_preserve_process(self):
        (self.cfg.parent.parent / "launch-settings.json").write_text('{"disable_gpu":"yes"}', encoding="utf-8")
        with mock.patch.object(engine, "close_profile") as stop:
            with self.assertRaisesRegex(RuntimeError, "must be true or false"):
                engine.restart_profile("account-2", exe=self.exe)
            stop.assert_not_called()

    def test_launch_rejects_malformed_config_before_spawn(self):
        self.cfg.write_text("broken = [", encoding="utf-8")
        with mock.patch.object(engine, "_spawn_desktop") as launch:
            with self.assertRaisesRegex(RuntimeError, "配置检查未通过"):
                engine.launch_profile("account-2", exe=self.exe)
            launch.assert_not_called()

    def test_valid_notify_accepts_both_key_spellings_individually(self):
        for spelling in ('"notify"', "notify"):
            self.cfg.write_text(spelling + ' = ["python", "hook.py"]\n', encoding="utf-8")
            engine.validate_launch("account-2")

    def test_main_restart_checks_config_before_stop(self):
        main = self.root / ".codex"
        main.mkdir()
        (main / "config.toml").write_text('"notify"=[]\nnotify=[]\n', encoding="utf-8")
        service = ManagerService()
        with mock.patch.object(engine.Path, "home", return_value=self.root), mock.patch.object(engine, "list_profiles", return_value=[]), mock.patch.object(engine, "_processes", return_value=[]), mock.patch.object(engine, "find_app_exe", return_value=self.exe), mock.patch.object(engine, "close_default_slot") as stop:
            with self.assertRaisesRegex(RuntimeError, "配置检查未通过"):
                service.perform("codex", None, "restart")
            stop.assert_not_called()

    def test_profile_environment_is_untouched_by_read_only_preflight(self):
        self.cfg.write_text('notify = ["current-hook"]\n', encoding="utf-8")
        original = self.cfg.read_bytes()
        engine.validate_launch("account-2")
        self.assertEqual(self.cfg.read_bytes(), original)
