# Instance Hub 1.4 — Windows quick start

Install the official Codex desktop app first. Place `AI-Instance-Hub.exe` in a
permanent writable folder and run it. This is a standalone EXE; no Python or
companion launcher is required for Codex setup and management.

1. Select Codex and click **添加账号** (Add account). Enter a display name and
   description. The Hub creates an independent profile and opens the official
   Codex window. Complete sign-in there and follow its browser authorization.
   **登录账号** (Sign in) reopens the selected account if setup is incomplete.
   Opening the window does not itself confirm successful authentication.
2. Return to the Hub to manage
   the main account and any created profiles. Closing its window sends it to the
   notification area; right-click its tray icon to exit the GUI.
3. Replace the EXE when updating. Keep the
   `CodexProfiles/`, `ClaudeProfiles/`, `state.json`, `account-display.json` and
   `usage_cache.json` files generated beside them. Profiles and login state are
   yours; the release ZIP contains no account folders or credentials.

Adding and signing in through the GUI currently supports Codex. Existing Claude
profiles can still be managed; Claude's snapshot sign-in flow remains in the
source console manager (`python main.py`).

The second Codex profile named `account-2` receives a distinct blue `2` taskbar
icon while it runs. Names and descriptions edited in the GUI are display-only;
they do not rename profile folders. Other profiles keep their original icon.

On Windows, unsigned executables can trigger SmartScreen. The source build path
is documented in `README.md` in the repository. If a GUI build is bound to an
existing installation, `instance-hub.json` beside the EXE can point to its
account-data root; this portable ZIP has no machine-specific binding.

This is a fork of `Zoltak-Dev/ai-multi-instance` (MIT). Original source:
https://github.com/Zoltak-Dev/ai-multi-instance

The GUI privately loads Baloo 2 and a renamed GenSen Rounded font. Their SIL
Open Font License notices are bundled with the GUI; source notices are in
`assets/fonts/`.
