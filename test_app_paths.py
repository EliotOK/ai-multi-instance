"""One-file extraction must never become the persistent profile directory."""
import json
from pathlib import Path
import tempfile
import unittest

from app_paths import resolve_data_root


class AppPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "_MEI-random"
        self.exe = self.root / "installed" / "hub.exe"
        self.accounts = self.root / "existing profiles"
        for path in (self.bundle, self.exe.parent, self.accounts):
            path.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_generic_exe_keeps_data_beside_executable(self):
        self.assertEqual(resolve_data_root(self.bundle, self.exe, True), self.exe.parent)

    def test_bound_build_reconnects_to_existing_profiles(self):
        (self.bundle / "hub-defaults.json").write_text(json.dumps({"data_root": str(self.accounts)}))
        self.assertEqual(resolve_data_root(self.bundle, self.exe, True), self.accounts)

    def test_relative_sidecar_and_override_take_precedence(self):
        (self.exe.parent / "instance-hub.json").write_text('{"data_root":"../existing profiles"}')
        self.assertEqual(resolve_data_root(self.bundle, self.exe, True), self.accounts)
        self.assertEqual(resolve_data_root(self.bundle, self.exe, True, str(self.bundle)), self.bundle)

    def test_invalid_sidecar_never_silently_switches_accounts(self):
        (self.exe.parent / "instance-hub.json").write_text('{"data_root":"missing"}')
        with self.assertRaisesRegex(ValueError, "无法读取账号目录设置"):
            resolve_data_root(self.bundle, self.exe, True)
