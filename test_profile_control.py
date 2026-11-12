"""Profile controls must never target the main app or a different account."""
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import engine


class ProfileControlTests(unittest.TestCase):
    def setUp(self):
        self.previous = engine.current_app()
        engine.set_app(engine.CODEX, persist=False)
        self.root_patch = mock.patch.object(engine, "PROFILES_DIR", Path(r"C:\profiles with spaces"))
        self.root_patch.start()
        self.exe = r"C:\Program Files\WindowsApps\OpenAI.Codex_26.1007.2314.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"

    def tearDown(self):
        self.root_patch.stop()
        engine.set_app(self.previous, persist=False)

    def test_process_filter_keeps_only_packaged_main_processes_and_exact_roots(self):
        rows = [(1, self.exe, '"app.exe"'),
                (2, self.exe, '"app.exe" "--user-data-dir=C:\\profiles with spaces\\account-2"'),
                (3, self.exe, '"app.exe" --user-data-dir="C:\\profiles with spaces\\other"'),
                (4, self.exe, '"app.exe" --type=renderer "--user-data-dir=C:\\profiles with spaces\\account-2"'),
                (5, r"C:\unrelated\ChatGPT.exe", '"app.exe" "--user-data-dir=C:\\profiles with spaces\\account-2"'),
                (6, self.exe, '"app.exe" "--user-data-dir=C:\\profiles with spaces-extra\\account-2"')]
        with mock.patch.object(engine, "_processes", return_value=rows):
            self.assertEqual(engine.running_profiles(strict=True), {"account-2": [2], "other": [3]})

    def test_close_kills_only_selected_profile_and_waits(self):
        with mock.patch.object(engine, "running_profiles", side_effect=[{"account-2": [2], "other": [3]}, {}]), mock.patch.object(engine, "_kill_pids", return_value=1) as kill:
            self.assertEqual(engine.close_profile("account-2", wait=15, strict=True), 1)
            kill.assert_called_once_with([2])

    def test_failed_process_query_does_not_claim_profile_stopped(self):
        with mock.patch.object(engine.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout="")):
            with self.assertRaisesRegex(RuntimeError, "Cannot inspect desktop processes"):
                engine.running_profiles(strict=True)

    def test_restart_stops_before_launch_and_does_not_launch_after_stop_failure(self):
        events = []
        with mock.patch.object(engine, "close_profile", side_effect=lambda *a, **k: events.append("close")), mock.patch.object(engine, "launch_profile", side_effect=lambda *a, **k: events.append("launch")):
            engine.restart_profile("account-2", exe=Path(self.exe))
            self.assertEqual(events, ["close", "launch"])
        with mock.patch.object(engine, "close_profile", side_effect=RuntimeError("stop failed")), mock.patch.object(engine, "launch_profile") as launch:
            with self.assertRaisesRegex(RuntimeError, "stop failed"):
                engine.restart_profile("account-2", exe=Path(self.exe))
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
