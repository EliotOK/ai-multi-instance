"""Check launch behavior and account isolation without opening desktop apps."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import engine
import profile_branding


class ProfileLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.previous = engine.current_app()
        self.project_patch = mock.patch.object(engine, "PROJECT_DIR", self.root)
        self.project_patch.start()

    def tearDown(self):
        self.project_patch.stop()
        engine.set_app(self.previous, persist=False)
        self.temp.cleanup()

    def launch(self, app, settings=None):
        engine.set_app(app, persist=False)
        profile = engine.create_profile("account with spaces")
        if settings is not None:
            (profile / "launch-settings.json").write_text(json.dumps(settings), encoding="utf-8")
        with mock.patch.object(engine.subprocess, "Popen") as popen:
            engine.launch_profile(profile.name, exe=Path("app.exe"))
        return profile, popen.call_args

    def test_codex_background_flags_keep_account_paths(self):
        profile, call = self.launch(engine.CODEX)
        self.assertEqual(call.args[0], ["app.exe", f"--user-data-dir={profile}",
                         "--disable-background-timer-throttling",
                         "--disable-renderer-backgrounding",
                         "--disable-backgrounding-occluded-windows"])
        self.assertEqual(call.kwargs["env"]["CODEX_HOME"], str(profile / ".codex"))
        self.assertEqual(call.kwargs["env"]["CODEX_ELECTRON_USER_DATA_PATH"], str(profile / "electron"))

    def test_claude_uses_original_launch_arguments(self):
        profile, call = self.launch(engine.CLAUDE, {"disable_gpu": True})
        self.assertEqual(call.args[0], ["app.exe", f"--user-data-dir={profile}"])

    def test_can_disable_workaround_and_enable_gpu_fallback(self):
        profile, call = self.launch(engine.CODEX, {"background_workaround": False, "disable_gpu": True})
        self.assertEqual(call.args[0], ["app.exe", f"--user-data-dir={profile}", "--disable-gpu"])

    def test_invalid_setting_does_not_launch(self):
        with self.assertRaisesRegex(RuntimeError, "disable_gpu must be true or false"):
            self.launch(engine.CODEX, {"disable_gpu": "false"})

    def test_pending_sidebar_sync_preserves_existing_ids_and_unrelated_state(self):
        engine.set_app(engine.CODEX, persist=False)
        profile = engine.create_profile("account with spaces")
        home = profile / ".codex"
        home.mkdir()
        state_path = home / ".codex-global-state.json"
        state_path.write_text(json.dumps({"selected-project": {"projectId": "legacy"},
            "local-projects": {"legacy": {"id": "legacy", "name": "Existing", "rootPaths": ["G:\\Shared"]}}}))
        (profile / "project-sync-pending.json").write_text(json.dumps({"projects": [
            {"id": "db-existing", "name": "Existing", "rootPaths": ["g:/shared/"]},
            {"id": "db-new", "name": "New", "rootPaths": ["D:\\New", "D:\\Secondary"]}]}))
        with mock.patch.object(engine, "running_profiles", return_value={}):
            engine.apply_pending_project_sync(profile.name)
        state = json.loads(state_path.read_text())
        self.assertEqual(set(state["local-projects"]), {"legacy", "db-new"})
        self.assertEqual(state["selected-project"], {"projectId": "legacy"})
        self.assertEqual(state["app-server-project-id-by-legacy-project-id-by-host"]["local:" + str(home)]["legacy"], "db-existing")
        self.assertEqual(state["local-projects"]["db-new"]["rootPaths"], ["D:\\New", "D:\\Secondary"])
        self.assertTrue((profile / "project-sync-applied.json").exists())
        self.assertTrue(state_path.with_name(state_path.name + ".projects-sync.bak").exists())
        (profile / "project-sync-pending.json").write_text((profile / "project-sync-applied.json").read_text())
        with mock.patch.object(engine, "running_profiles", return_value={}):
            engine.apply_pending_project_sync(profile.name)
        self.assertEqual(len(json.loads(state_path.read_text())["local-projects"]), 2)

    def test_pending_sidebar_sync_waits_for_profile_to_close(self):
        engine.set_app(engine.CODEX, persist=False)
        profile = engine.create_profile("account with spaces")
        pending = profile / "project-sync-pending.json"
        pending.write_text("{}")
        with mock.patch.object(engine, "running_profiles", return_value={profile.name: [123]}):
            engine.apply_pending_project_sync(profile.name)
        self.assertTrue(pending.exists())

    def test_frozen_cli_and_shortcut_use_sibling_hub_for_profile_icon(self):
        engine.set_app(engine.CODEX, persist=False)
        for binary in ("ai-multi-instance.exe", "launcher.exe", "AI-Instance-Hub.exe"):
            with self.subTest(binary=binary), \
                 mock.patch.object(engine.sys, "frozen", True, create=True), \
                 mock.patch.object(engine.sys, "executable", str(self.root / binary)), \
                 mock.patch.object(profile_branding, "worker_present", return_value=False), \
                 mock.patch.object(engine, "_spawn_desktop") as spawn:
                engine.ensure_profile_icon("account-2")
                self.assertEqual(spawn.call_args.args[0], self.root / "AI-Instance-Hub.exe")


if __name__ == "__main__":
    unittest.main()
