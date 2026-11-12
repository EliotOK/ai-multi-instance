"""Windows taskbar identity, notification-area icon, and single-instance gate."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import queue
import time
import uuid

from app_paths import RESOURCE_DIR, data_root

TITLE = "AI 账号启动器"
APP_ID = "Local.AI.InstanceHub"
ROOT = data_root()
ICON = RESOURCE_DIR / "assets" / "instance-hub.ico"
KEY = hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:20]
CLASS_NAME = "AI.InstanceHub.Notify." + KEY
SHOW_MESSAGE = 0x804E
TRAY_MESSAGE = 0x804D
WNDPROC = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class GUID(c.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", w.BYTE * 8)]


class NotifyIconData(c.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
               ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
               ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
               ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
               ("guidItem", GUID), ("hBalloonIcon", w.HICON)]


class WindowClass(c.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", c.c_int),
               ("cbWndExtra", c.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
               ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
               ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


def function(library, name, arguments, result):
    value = getattr(library, name)
    value.argtypes = arguments
    value.restype = result
    return value


class WindowsApi:
    def __init__(self):
        self.user = c.WinDLL("user32", use_last_error=True)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.shell = c.WinDLL("shell32", use_last_error=True)
        self.find = function(self.user, "FindWindowW", [w.LPCWSTR, w.LPCWSTR], w.HWND)
        self.post = function(self.user, "PostMessageW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL)
        self.show = function(self.user, "ShowWindow", [w.HWND, c.c_int], w.BOOL)
        self.foreground = function(self.user, "SetForegroundWindow", [w.HWND], w.BOOL)
        self.ancestor = function(self.user, "GetAncestor", [w.HWND, w.UINT], w.HWND)
        self.get_style = function(self.user, "GetWindowLongPtrW", [w.HWND, c.c_int], c.c_ssize_t)
        self.set_style = function(self.user, "SetWindowLongPtrW", [w.HWND, c.c_int, c.c_ssize_t], c.c_ssize_t)
        self.position = function(self.user, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT], w.BOOL)
        self.default = function(self.user, "DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], c.c_ssize_t)
        self.module = function(self.kernel, "GetModuleHandleW", [w.LPCWSTR], w.HMODULE)
        self.register = function(self.user, "RegisterClassW", [c.POINTER(WindowClass)], w.WORD)
        self.create = function(self.user, "CreateWindowExW", [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p], w.HWND)
        self.destroy = function(self.user, "DestroyWindow", [w.HWND], w.BOOL)
        self.unregister = function(self.user, "UnregisterClassW", [w.LPCWSTR, w.HINSTANCE], w.BOOL)
        self.load_icon = function(self.user, "LoadImageW", [w.HINSTANCE, w.LPCWSTR, w.UINT, c.c_int, c.c_int, w.UINT], w.HANDLE)
        self.destroy_icon = function(self.user, "DestroyIcon", [w.HICON], w.BOOL)
        self.notify = function(self.shell, "Shell_NotifyIconW", [w.DWORD, c.POINTER(NotifyIconData)], w.BOOL)
        self.message = function(self.user, "RegisterWindowMessageW", [w.LPCWSTR], w.UINT)
        self.create_menu = function(self.user, "CreatePopupMenu", [], w.HMENU)
        self.append_menu = function(self.user, "AppendMenuW", [w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR], w.BOOL)
        self.track_menu = function(self.user, "TrackPopupMenu", [w.HMENU, w.UINT, c.c_int, c.c_int, c.c_int, w.HWND, c.c_void_p], w.UINT)
        self.destroy_menu = function(self.user, "DestroyMenu", [w.HMENU], w.BOOL)
        self.cursor = function(self.user, "GetCursorPos", [c.POINTER(w.POINT)], w.BOOL)


def set_identity():
    shell = c.WinDLL("shell32")
    setter = function(shell, "SetCurrentProcessExplicitAppUserModelID", [w.LPCWSTR], c.c_long)
    if setter(APP_ID) < 0:
        raise OSError("Cannot set launcher taskbar identity")


class SingleInstance:
    def __init__(self):
        self.api = WindowsApi()
        self.create_mutex = function(self.api.kernel, "CreateMutexW", [c.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE)
        self.close_handle = function(self.api.kernel, "CloseHandle", [w.HANDLE], w.BOOL)
        self.release = function(self.api.kernel, "ReleaseMutex", [w.HANDLE], w.BOOL)
        self.handle = None
        self.owner = False

    def acquire(self):
        c.set_last_error(0)
        self.handle = self.create_mutex(None, True, "Local\\AI.InstanceHub." + KEY)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        self.owner = c.get_last_error() != 183
        if self.owner:
            return True
        for _ in range(20):
            notifier = self.api.find(CLASS_NAME, "InstanceHubNotifier")
            if notifier:
                self.api.post(notifier, SHOW_MESSAGE, 0, 0)
                return False
            time.sleep(.1)
        window = self.api.find(None, TITLE)
        if window:
            self.api.show(window, 9)
            self.api.foreground(window)
        return False

    def close(self):
        if self.handle:
            if self.owner:
                self.release(self.handle)
            self.close_handle(self.handle)
            self.handle = None


class DesktopShell:
    def __init__(self, root, identity_suffix=None):
        self.root = root
        self.api = WindowsApi()
        self.events = queue.Queue()
        self.hwnd = None
        self.icon = None
        self.added = False
        self.class_name = CLASS_NAME + (".Test." + identity_suffix if identity_suffix else "")
        self.identity_key = KEY + (":" + identity_suffix if identity_suffix else "")
        self.instance = self.api.module(None)
        self.taskbar_created = self.api.message("TaskbarCreated")
        self.callback = WNDPROC(self._procedure)
        self.data = NotifyIconData()
        root.update_idletasks()
        self.root_hwnd = self.api.ancestor(root.winfo_id(), 2)
        style = self.api.get_style(self.root_hwnd, -20)
        self.api.set_style(self.root_hwnd, -20, (style | 0x40000) & ~0x80)
        self.api.set_style(self.root_hwnd, -8, 0)
        self.api.position(self.root_hwnd, None, 0, 0, 0, 0, 0x37)
        try:
            dwm = c.WinDLL("dwmapi")
            attribute = function(dwm, "DwmSetWindowAttribute", [w.HWND, w.DWORD, c.c_void_p, w.DWORD], c.c_long)
            dark = c.c_int(1)
            attribute(self.root_hwnd, 20, c.byref(dark), c.sizeof(dark))
        except OSError:
            pass
        window_class = WindowClass()
        window_class.lpfnWndProc = self.callback
        window_class.hInstance = self.instance
        window_class.lpszClassName = self.class_name
        if not self.api.register(c.byref(window_class)):
            raise c.WinError(c.get_last_error())
        self.hwnd = self.api.create(0x80, self.class_name, "InstanceHubNotifier", 0,
                                   0, 0, 0, 0, None, None, self.instance, None)
        if not self.hwnd:
            self.close()
            raise c.WinError(c.get_last_error())
        self.icon = self.api.load_icon(None, str(ICON), 1, 32, 32, 0x10)
        if not self.icon:
            self.close()
            raise OSError("Cannot load launcher icon")
        self.data.cbSize = c.sizeof(NotifyIconData)
        self.data.hWnd = self.hwnd
        self.data.uID = 1
        self.data.uFlags = 1 | 2 | 4 | 0x20 | 0x80
        self.data.uCallbackMessage = TRAY_MESSAGE
        self.data.hIcon = self.icon
        self.data.szTip = "AI 账号启动器 · 点击打开"
        self.data.guidItem = GUID.from_buffer_copy(uuid.uuid5(uuid.NAMESPACE_URL, "instance-hub:" + self.identity_key).bytes_le)
        self._add()

    def _add(self):
        self.added = bool(self.api.notify(0, c.byref(self.data)))
        if self.added:
            self.data.uVersion = 4
            self.api.notify(4, c.byref(self.data))

    def _procedure(self, hwnd, message, wparam, lparam):
        if message == SHOW_MESSAGE:
            self.events.put("show")
            return 0
        if message == self.taskbar_created:
            self._add()
            return 0
        if message == TRAY_MESSAGE:
            event = lparam & 0xffff
            if event in (0x202, 0x203, 0x400, 0x401):
                self.events.put("show")
            elif event in (0x205, 0x7B):
                self._menu()
            return 0
        return self.api.default(hwnd, message, wparam, lparam)

    def _menu(self):
        menu = self.api.create_menu()
        try:
            self.api.append_menu(menu, 0, 1, "打开启动器")
            self.api.append_menu(menu, 0x800, 0, None)
            self.api.append_menu(menu, 0, 2, "退出启动器")
            point = w.POINT()
            self.api.cursor(c.byref(point))
            self.api.foreground(self.hwnd)
            command = self.api.track_menu(menu, 0x100 | 2, point.x, point.y, 0, self.hwnd, None)
            self.api.post(self.hwnd, 0, 0, 0)
            if command in (1, 2):
                self.events.put("show" if command == 1 else "quit")
        finally:
            self.api.destroy_menu(menu)

    def diagnostics(self):
        return {"pid": os.getpid(), "app_id": APP_ID, "title": TITLE, "icon": str(ICON),
                "tray_added": self.added, "taskbar_appwindow": bool(self.api.get_style(self.root_hwnd, -20) & 0x40000),
                "toolwindow": bool(self.api.get_style(self.root_hwnd, -20) & 0x80),
                "owner": self.api.get_style(self.root_hwnd, -8)}

    def close(self):
        if self.added:
            self.api.notify(2, c.byref(self.data))
            self.added = False
        if self.hwnd:
            self.api.destroy(self.hwnd)
            self.hwnd = None
        if self.icon:
            self.api.destroy_icon(self.icon)
            self.icon = None
        self.api.unregister(self.class_name, self.instance)
