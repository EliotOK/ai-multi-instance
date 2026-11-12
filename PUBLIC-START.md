# Windows quick start

This package combines the upstream Claude/Codex multi-instance CLI with the
Instance Hub GUI. It is a portable ZIP. Extract all three executables into the
same folder. Install the official Codex or Claude Desktop app first.

1. Run `ai-multi-instance.exe` once. Choose Codex or Claude, then use action `7`
   to create a separate profile. Follow its sign-in prompt. You can create more
   profiles later with the same CLI.
2. Run `AI-Instance-Hub.exe` to open the GUI. Select Codex or Claude and manage
   the main account and any created profiles. Closing its window sends it to the
   notification area; right-click its tray icon to exit the GUI.
3. Keep all three executables in the same folder when updating. Keep the
   `CodexProfiles/`, `ClaudeProfiles/`, `state.json`, `account-display.json` and
   `usage_cache.json` files generated beside them. Profiles and login state are
   yours; the release ZIP contains no account folders or credentials.

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
