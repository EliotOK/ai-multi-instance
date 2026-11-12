"""Load rounded fonts privately for this process; no system installation."""
import ctypes
from ctypes import wintypes
from tkinter import font as tkfont

from app_paths import RESOURCE_DIR


class PrivateFonts:
    def __init__(self, root):
        self.paths = []
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.gdi.AddFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        self.gdi.AddFontResourceExW.restype = ctypes.c_int
        self.gdi.RemoveFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        self.gdi.RemoveFontResourceExW.restype = wintypes.BOOL
        for name in ("Baloo2-ExtraBold.ttf", "InstanceHubRounded-Bold.otf"):
            path = RESOURCE_DIR / "assets" / "fonts" / name
            if self.gdi.AddFontResourceExW(str(path), 0x10, None):
                self.paths.append(path)
        families = set(tkfont.families(root))
        self.display = "Baloo 2" if "Baloo 2" in families else "Segoe UI"
        self.rounded = "Instance Hub Rounded" if "Instance Hub Rounded" in families else "Microsoft YaHei UI"

    def close(self):
        for path in self.paths:
            self.gdi.RemoveFontResourceExW(str(path), 0x10, None)
        self.paths.clear()
