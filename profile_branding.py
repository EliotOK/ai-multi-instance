"""Profile-scoped Windows icons; official application files stay untouched."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import engine
from account_display import DisplayStore
from app_paths import RESOURCE_DIR, resolve_data_root
from windows_shell import GUID, WindowsApi, function


class PropertyKey(c.Structure):
    _fields_ = [("fmtid", GUID), ("pid", w.DWORD)]


class VariantValue(c.Union):
    _fields_ = [("string", c.c_void_p), ("storage", c.c_byte * 16)]


class PropVariant(c.Structure):
    _fields_ = [("vt", w.WORD), ("r1", w.WORD), ("r2", w.WORD), ("r3", w.WORD), ("value", VariantValue)]


def guid(value):
    return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def check(hr):
    if hr < 0:
        raise OSError(f"Windows property operation failed: 0x{hr & 0xffffffff:08X}")


class WindowProperties:
    def __init__(self, hwnd):
        self.ole = c.WinDLL("ole32")
        self.clear = function(self.ole,"PropVariantClear",[c.POINTER(PropVariant)],c.c_long)
        initialize = function(self.ole,"CoInitializeEx",[c.c_void_p,w.DWORD],c.c_long)
        hr=initialize(None,2)
        self.uninitialize=hr in (0,1)
        if hr<0 and (hr & 0xffffffff)!=0x80010106:
            check(hr)
        self.pointer=c.c_void_p()
        getter=function(c.WinDLL("shell32"),"SHGetPropertyStoreForWindow",
                        [w.HWND,c.POINTER(GUID),c.POINTER(c.c_void_p)],c.c_long)
        iid=guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
        try:
            check(getter(hwnd,c.byref(iid),c.byref(self.pointer)))
        except Exception:
            self.close()
            raise
        table=c.cast(self.pointer,c.POINTER(c.POINTER(c.c_void_p))).contents
        self.get_value=c.WINFUNCTYPE(c.c_long,c.c_void_p,c.POINTER(PropertyKey),c.POINTER(PropVariant))(table[5])
        self.set_value=c.WINFUNCTYPE(c.c_long,c.c_void_p,c.POINTER(PropertyKey),c.POINTER(PropVariant))(table[6])
        self.commit=c.WINFUNCTYPE(c.c_long,c.c_void_p)(table[7])
        self.release=c.WINFUNCTYPE(w.ULONG,c.c_void_p)(table[2])

    def key(self, number):
        return PropertyKey(guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),number)

    def get(self, number):
        value=PropVariant()
        try:
            check(self.get_value(self.pointer,c.byref(self.key(number)),c.byref(value)))
            return c.wstring_at(value.value.string) if value.vt==31 and value.value.string else None
        finally:
            self.clear(c.byref(value))

    def set(self, number, text):
        value=PropVariant()
        buffer=None
        if text is not None:
            buffer=c.create_unicode_buffer(text)
            value.vt=31
            value.value.string=c.cast(buffer,c.c_void_p).value
        # SetValue copies the const PROPVARIANT. This buffer is Python-owned;
        # PropVariantClear is only for the COM-allocated GetValue result.
        check(self.set_value(self.pointer,c.byref(self.key(number)),c.byref(value)))

    def close(self):
        if getattr(self,"pointer",None) and self.pointer.value:
            self.release(self.pointer)
            self.pointer=c.c_void_p()
        if getattr(self,"uninitialize",False):
            self.ole.CoUninitialize()
            self.uninitialize=False

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()


class BrandingApi(WindowsApi):
    def __init__(self):
        super().__init__()
        self.enum_callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        self.enum=function(self.user,"EnumWindows",[self.enum_callback,w.LPARAM],w.BOOL)
        self.pid=function(self.user,"GetWindowThreadProcessId",[w.HWND,c.POINTER(w.DWORD)],w.DWORD)
        self.visible=function(self.user,"IsWindowVisible",[w.HWND],w.BOOL)
        self.valid=function(self.user,"IsWindow",[w.HWND],w.BOOL)
        self.class_name=function(self.user,"GetClassNameW",[w.HWND,w.LPWSTR,c.c_int],c.c_int)
        self.send=function(self.user,"SendMessageTimeoutW",[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,c.POINTER(c.c_size_t)],c.c_size_t)

    def windows(self):
        values=[]
        def collect(hwnd,param):
            pid=w.DWORD()
            self.pid(hwnd,c.byref(pid))
            name=c.create_unicode_buffer(128)
            self.class_name(hwnd,name,len(name))
            values.append({"hwnd":hwnd,"pid":pid.value,"class":name.value,
                           "visible":bool(self.visible(hwnd)),"owner":self.get_style(hwnd,-8),
                           "toolwindow":bool(self.get_style(hwnd,-20)&0x80)})
            return True
        callback=self.enum_callback(collect)
        if not self.enum(callback,0):
            raise c.WinError(c.get_last_error())
        return values

    def window_message(self,hwnd,number,wparam,lparam=0):
        result=c.c_size_t()
        if not self.send(hwnd,number,wparam,lparam,2|0x20,1500,c.byref(result)):
            raise OSError("Client window did not respond to icon update")
        return result.value

    def window_pid(self,hwnd):
        current=w.DWORD()
        self.pid(hwnd,c.byref(current))
        return current.value


def eligible_windows(windows, owned_pids):
    return [v for v in windows if v["pid"] in owned_pids and v["class"]=="Chrome_WidgetWin_1"
            and v["visible"] and not v["owner"] and not v["toolwindow"]]


def profile_key(name):
    root=engine.PROFILES_DIR / name
    return hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()[:20]


def identity(name):
    return "Local.AI.CodexProfile."+profile_key(name)


def mutex_name(name):
    return "Local\\AI.InstanceHub.Icon."+profile_key(name)


def worker_present(name):
    api=WindowsApi()
    create=function(api.kernel,"CreateMutexW",[c.c_void_p,w.BOOL,w.LPCWSTR],w.HANDLE)
    close=function(api.kernel,"CloseHandle",[w.HANDLE],w.BOOL)
    c.set_last_error(0)
    handle=create(None,False,mutex_name(name))
    if not handle:
        raise c.WinError(c.get_last_error())
    exists=c.get_last_error()==183
    close(handle)
    return exists


def icon_path(name):
    if engine.current_app().key!="codex" or name!="account-2":
        raise ValueError("Only the second Codex client has a custom icon")
    target=engine.PROFILES_DIR/name/"branding"/"client.ico"
    original=(RESOURCE_DIR/"assets"/"codex-account-2.ico").read_bytes()
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists() or target.read_bytes()!=original:
        temp=target.with_suffix(".tmp")
        temp.write_bytes(original)
        temp.replace(target)
    return target


def relaunch_command(name):
    args=["--app=codex","--open-account",name]
    default=resolve_data_root(RESOURCE_DIR,Path(sys.executable),bool(getattr(sys,"frozen",False)))
    if default.resolve()!=engine.PROJECT_DIR.resolve():
        args.extend(("--data-dir",str(engine.PROJECT_DIR)))
    if getattr(sys,"frozen",False):
        command=[sys.executable,*args]
    else:
        command=[engine.pythonw_path(),str(RESOURCE_DIR/"manager.pyw"),*args]
    return subprocess.list2cmdline(command)


class ProfileBranding:
    def __init__(self,name,api=None):
        self.name=name
        self.api=api or BrandingApi()
        self.path=icon_path(name)
        self.icons={size:self.api.load_icon(None,str(self.path),1,size,size,0x10) for size in (16,32)}
        if not all(self.icons.values()):
            self.close()
            raise OSError("Cannot load profile icon")
        self.applied={}

    def apply(self,owned_pids,label="第二账号"):
        windows=eligible_windows(self.api.windows(),set(owned_pids))
        applied=[]
        self.applied={hwnd:value for hwnd,value in self.applied.items() if self.api.valid(hwnd) and self.api.window_pid(hwnd)==value["pid"]}
        for value in windows:
            hwnd=value["hwnd"]
            # Re-check ownership immediately before crossing the window boundary.
            current=w.DWORD()
            self.api.pid(hwnd,c.byref(current))
            if current.value not in owned_pids:
                continue
            if hwnd not in self.applied:
                self.applied[hwnd]={"pid":current.value,"icons":[self.api.window_message(hwnd,0x7F,i) for i in (0,1)]}
            with WindowProperties(hwnd) as store:
                desired={2:relaunch_command(self.name),3:str(self.path)+",0",4:"Codex · "+label,5:identity(self.name)}
                if "properties" not in self.applied[hwnd]:
                    self.applied[hwnd]["properties"]={key:store.get(key) for key in desired}
                for key in (2,3,4,5):
                    if store.get(key)!=desired[key]:
                        store.set(key,desired[key])
                check(store.commit(store.pointer))
            for index,size in ((0,16),(1,32)):
                if self.api.window_message(hwnd,0x7F,index)!=self.icons[size]:
                    self.api.window_message(hwnd,0x80,index,self.icons[size])
            applied.append({"hwnd":hwnd,"pid":current.value})
        return applied

    def close(self):
        if hasattr(self,"applied"):
            for hwnd,old in self.applied.items():
                if not self.api.valid(hwnd) or self.api.window_pid(hwnd)!=old["pid"]:
                    continue
                try:
                    for index in (0,1):
                        self.api.window_message(hwnd,0x80,index,old["icons"][index])
                    with WindowProperties(hwnd) as store:
                        for key,value in old.get("properties",{}).items():
                            store.set(key,value)
                        check(store.commit(store.pointer))
                except OSError:
                    pass
            self.applied={}
        for icon in getattr(self,"icons",{}).values():
            if icon:
                self.api.destroy_icon(icon)
        self.icons={}


def run_worker(name):
    if name!="account-2" or engine.current_app().key!="codex" or not (engine.PROFILES_DIR/name).is_dir():
        raise ValueError("Invalid second-client profile")
    api=WindowsApi()
    create=function(api.kernel,"CreateMutexW",[c.c_void_p,w.BOOL,w.LPCWSTR],w.HANDLE)
    close=function(api.kernel,"CloseHandle",[w.HANDLE],w.BOOL)
    release=function(api.kernel,"ReleaseMutex",[w.HANDLE],w.BOOL)
    c.set_last_error(0)
    handle=create(None,True,mutex_name(name))
    if not handle:
        raise c.WinError(c.get_last_error())
    if c.get_last_error()==183:
        close(handle)
        return
    branding=None
    seen=False
    deadline=time.monotonic()+30
    report=engine.PROFILES_DIR/name/"branding"/"runtime.json"
    try:
        branding=ProfileBranding(name)
        while True:
            pids=engine.running_profiles(strict=True).get(name,[])
            if not pids:
                if seen or time.monotonic()>deadline:
                    break
                time.sleep(.5)
                continue
            seen=True
            display=DisplayStore().for_app("codex").get("profile:"+name,{})
            windows=branding.apply(pids,display.get("label","第二账号"))
            if windows:
                report.write_text(json.dumps({"worker_pid":os.getpid(),"client_pids":pids,"windows":windows,
                    "app_id":identity(name),"icon":str(branding.path),"applied":True},ensure_ascii=False,indent=2),encoding="utf-8")
            time.sleep(2)
    except Exception as exc:
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps({"applied":False,"error":str(exc)},ensure_ascii=False),encoding="utf-8")
    finally:
        if branding:
            branding.close()
        release(handle)
        close(handle)
