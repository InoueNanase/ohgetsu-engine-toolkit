# -*- coding: utf-8 -*-
"""GDI 字形渲染画布（Windows）

用 CreateDIBSection + TextOutW 把字符画进 32bpp 位图，返回灰度墨迹矩阵。
不依赖 Pillow / FreeType，只用系统 GDI —— 好处是能拿到和游戏一致的 hinting/抗锯齿。

用法（自检）:
    python gdirender.py "永" "Microsoft YaHei" 24
"""
import ctypes
import sys
from ctypes import wintypes

gdi32 = ctypes.WinDLL("gdi32")

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
gdi32.GdiFlush.restype = wintypes.BOOL

DEFAULT_CW, DEFAULT_CH = 48, 40
CLEARTYPE_QUALITY = 5
ANTIALIASED_QUALITY = 4


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]


class Canvas:
    """可复用的 GDI 画布：draw(ch, x, y) -> 灰度矩阵（0=纸, 255=墨）"""

    def __init__(self, face="Microsoft YaHei", height=24, weight=400,
                 cw=None, ch=None, quality=ANTIALIASED_QUALITY):
        self.cw = cw or DEFAULT_CW
        self.ch = ch or DEFAULT_CH
        self.hdc = gdi32.CreateCompatibleDC(None)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = self.cw
        bi.bmiHeader.biHeight = -self.ch          # 负值 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0
        self.bits = ctypes.c_void_p()
        self.hbmp = gdi32.CreateDIBSection(self.hdc, ctypes.byref(bi), 0,
                                           ctypes.byref(self.bits), None, 0)
        gdi32.SelectObject(self.hdc, self.hbmp)
        # 字高传负值 = 字符高度（不含内部行距），与游戏请求的黑盒尺寸一致
        self.hf = gdi32.CreateFontW(-height, 0, 0, 0, weight, 0, 0, 0,
                                    0x80, 0, 0, quality, 0, face)
        gdi32.SelectObject(self.hdc, self.hf)
        gdi32.SetBkMode(self.hdc, 1)               # TRANSPARENT
        gdi32.SetTextColor(self.hdc, 0x000000)
        self.buf = (ctypes.c_ubyte * (self.cw * self.ch * 4)).from_address(self.bits.value)

    def draw(self, ch, x=0, y=0):
        """白底黑字，返回 255-v 的墨迹灰度"""
        buf, cw, chh = self.buf, self.cw, self.ch
        for i in range(0, cw * chh * 4, 4):
            buf[i] = buf[i + 1] = buf[i + 2] = buf[i + 3] = 255
        gdi32.TextOutW(self.hdc, x, y, ch, 1)
        gdi32.GdiFlush()
        rows = []
        for yy in range(chh):
            base = yy * cw * 4
            rows.append([255 - buf[base + xx * 4] for xx in range(cw)])
        return rows


def mask(rows, thr=100):
    return [[1 if v > thr else 0 for v in r] for r in rows]


def ink_bbox(rows, thr=20):
    """墨迹外接框 (x0, y0, x1, y1)，无墨迹返回 None"""
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v > thr:
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    return None if x1 < 0 else (x0, y0, x1, y1)


if __name__ == "__main__":
    ch = sys.argv[1] if len(sys.argv) > 1 else "永"
    face = sys.argv[2] if len(sys.argv) > 2 else "Microsoft YaHei"
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    cv = Canvas(face, size, cw=size * 2 + 16, ch=size * 2 + 16)
    rows = cv.draw(ch, 8, 8)
    bb = ink_bbox(rows)
    print(f"{ch!r} @ {face} {size}px  画布 {cv.cw}x{cv.ch}  墨迹框 {bb}")
    if bb:
        x0, y0, x1, y1 = bb
        for y in range(y0, y1 + 1):
            print("".join("#" if rows[y][x] > 100 else ("+" if rows[y][x] > 30 else ".")
                          for x in range(x0, x1 + 1)))
