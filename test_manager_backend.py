"""Check account ownership, unknown-state handling, and isolated launches."""
import os
import unittest
from pathlib import Path
from unittest import mock

import engine
from manager_backend import ManagerService


class ManagerBackendTests(unittest.TestCase):
    def setUp(self):
        self.previous = engine.current_app()
        self.service = ManagerService()
        self.root_patch = mock.patch.object(engine, "PROJECT_DIR", Path(r"C:\profiles"))
        self.root_patch.start()
        self.exe = r"C:\Program Files\WindowsApps\OpenAI.Codex_26.1007.2314.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"

    def tearDown(self):
        self.root_patch.stop()
        engine.set_app(self.previous, persist=False)

    def records(self):
        return [(1, self.exe, '"app.exe"'),
                (2, self.exe, '"app.exe" --user-data-dir=C:\\profiles\\CodexProfiles\\account-2'),
                (3, self.exe, '"app.exe" --type=renderer --user-data-dir=C:\\profiles\\CodexProfiles\\account-2'),
                (4, self.exe, '"app.exe" --user-data-dir=C:\\profiles\\CodexProfiles\\account-3')]

    def snapshot_context(self):
        return mock.patch.object(engine, "list_profiles", return_value=[Path("account-2"), Path("account-3")])

    def test_snapshot_scans_once_and_keeps_main_and_profiles_separate(self):
        with self.snapshot_context(), mock.patch.object(engine, "_processes", return_value=self.records()) as scan:
            snapshot = self.service.snapshot("codex")
        self.assertEqual([(a.name, a.pids) for a in snapshot.accounts], [(None, (1,)), ("account-2", (2,)), ("account-3", (4,))])
        scan.assert_called_once_with("ChatGPT.exe", strict=True)

    def test_unknown_status_blocks_actions(self):
        with self.snapshot_context(), mock.patch.object(engine, "_processes", side_effect=RuntimeError("denied")), mock.patch.object(engine, "close_profile") as close:
            self.assertTrue(self.service.snapshot("codex").error)
            with self.assertRaisesRegex(RuntimeError, "无法读取运行状态"):
                self.service.perform("codex", "account-2", "close")
            close.assert_not_called()

    def test_stop_profile_never_stops_main(self):
        with self.snapshot_context(), mock.patch.object(engine, "_processes", return_value=self.records()), mock.patch.object(engine, "close_profile") as profile_close, mock.patch.object(engine, "close_default_slot") as main_close:
            self.service.perform("codex", "account-2", "close")
            profile_close.assert_called_once_with("account-2", wait=15, strict=True)
            main_close.assert_not_called()

    def test_stop_main_never_stops_profiles(self):
        with self.snapshot_context(), mock.patch.object(engine, "_processes", return_value=self.records()), mock.patch.object(engine, "close_profile") as profile_close, mock.patch.object(engine, "close_default_slot") as main_close:
            self.service.perform("codex", None, "close")
            main_close.assert_called_once_with(wait=15, strict=True)
            profile_close.assert_not_called()

    def test_failed_app_discovery_does_not_stop_account_for_restart(self):
        with self.snapshot_context(), mock.patch.object(engine, "_processes", return_value=self.records()), mock.patch.object(engine, "find_app_exe", return_value=None), mock.patch.object(engine, "restart_profile") as restart:
            with self.assertRaisesRegex(RuntimeError, "未安装"):
                self.service.perform("codex", "account-2", "restart")
            restart.assert_not_called()

    def test_main_restart_waits_for_exit_before_launch(self):
        events = []
        with self.snapshot_context(), mock.patch.object(engine, "_processes", return_value=self.records()), mock.patch.object(engine, "find_app_exe", return_value=Path(self.exe)), mock.patch.object(engine, "close_default_slot", side_effect=lambda **kw: events.append("close")), mock.patch.object(engine, "launch_default_slot", side_effect=lambda **kw: events.append("launch")), mock.patch.object(engine, "restart_profile") as profile_restart:
            self.service.perform("codex", None, "restart")
            self.assertEqual(events, ["close", "launch"])
            profile_restart.assert_not_called()

    def test_main_launch_removes_inherited_profile_environment(self):
        engine.set_app(engine.CODEX, persist=False)
        with mock.patch.dict(os.environ, {"CODEX_HOME": r"C:\profile\.codex", "CODEX_ELECTRON_USER_DATA_PATH": r"C:\profile\electron", "KEEP_ME": "yes"}), mock.patch.object(engine.subprocess, "Popen") as popen:
            engine.launch_default_slot(exe=Path(self.exe))
            env = popen.call_args.kwargs["env"]
            self.assertNotIn("CODEX_HOME", env)
            self.assertNotIn("CODEX_ELECTRON_USER_DATA_PATH", env)
            self.assertEqual(env["KEEP_ME"], "yes")


if __name__ == "__main__":
    unittest.main()
