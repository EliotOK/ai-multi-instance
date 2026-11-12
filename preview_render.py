"""Render only our own Tk window for reproducible UI preview / packaged QA."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path

from PIL import Image
from windows_shell import function


class Header(c.Structure):
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG), ("planes", w.WORD),
                ("bits", w.WORD), ("compression", w.DWORD), ("image_size", w.DWORD),
                ("x", w.LONG), ("y", w.LONG), ("used", w.DWORD), ("important", w.DWORD)]


class Info(c.Structure):
    _fields_ = [("header", Header), ("colors", w.DWORD * 3)]


def capture_window(root, output: Path):
    user, gdi = c.WinDLL("user32"), c.WinDLL("gdi32")
    ancestor = function(user,"GetAncestor",[w.HWND,w.UINT],w.HWND)
    rect_fn = function(user,"GetWindowRect",[w.HWND,c.POINTER(w.RECT)],w.BOOL)
    get_dc = function(user,"GetWindowDC",[w.HWND],w.HDC)
    release = function(user,"ReleaseDC",[w.HWND,w.HDC],c.c_int)
    create_dc = function(gdi,"CreateCompatibleDC",[w.HDC],w.HDC)
    create_bitmap = function(gdi,"CreateCompatibleBitmap",[w.HDC,c.c_int,c.c_int],w.HBITMAP)
    select = function(gdi,"SelectObject",[w.HDC,w.HANDLE],w.HANDLE)
    print_window = function(user,"PrintWindow",[w.HWND,w.HDC,w.UINT],w.BOOL)
    delete_dc = function(gdi,"DeleteDC",[w.HDC],w.BOOL)
    delete_obj = function(gdi,"DeleteObject",[w.HANDLE],w.BOOL)
    get_bits = function(gdi,"GetDIBits",[w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.POINTER(Info),w.UINT],c.c_int)
    hwnd = ancestor(root.winfo_id(),2)
    rect = w.RECT()
    if not rect_fn(hwnd,c.byref(rect)):
        raise OSError("Cannot read preview geometry")
    width,height = rect.right-rect.left,rect.bottom-rect.top
    source = get_dc(hwnd)
    target = create_dc(source)
    bitmap = create_bitmap(source,width,height)
    old = select(target,bitmap)
    try:
        if not print_window(hwnd,target,2):
            raise OSError("Cannot render launcher preview")
        select(target,old)
        info = Info()
        info.header = Header(c.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0)
        pixels = c.create_string_buffer(width*height*4)
        if get_bits(source,bitmap,0,height,pixels,c.byref(info),0) != height:
            raise OSError("Cannot read preview pixels")
        image = Image.frombuffer("RGB",(width,height),pixels.raw,"raw","BGRX",0,1)
        if len(image.getcolors(width*height) or []) <= 20:
            raise OSError("Launcher preview is blank")
        image.save(output)
    finally:
        select(target,old)
        delete_obj(bitmap)
        delete_dc(target)
        release(hwnd,source)
