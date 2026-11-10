# -*- coding: utf-8 -*-
"""字形渲染管线 —— 把汉字渲染成可直接写进字体图集的灰度点阵

关键不是渲染 API，而是「取样窗口」的取法：

  1. 墨迹并集窗口：先渲染一组参考字，取墨迹并集外接框，按 max(w,h)*1.04 取正方形。
     不能用字身框 —— 雅黑等字体的墨迹会超出字身框（尤其底部），直接裁会切笔画。
  2. 逐字扩窗：单字墨迹超出该窗口时，把窗口外扩到完全容纳（每边留 1px）。
  3. 缩放：super = 超采样后盒式下采样；native = 直接用 ANTIALIASED_QUALITY 渲染。
  4. gamma：v' = (v/255)^γ * 255，γ<1 加粗墨迹。

用法:
    python glyph_render.py --chars used_chars.txt --out glyphs/ \
        [--face "Microsoft YaHei"] [--size 24] [--mode native] [--gamma 0.95]
        [--charmap charmap.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gdirender as G
import font_tool as FT

REF = "永国目田由甲申一丨丶口中日月目自明言高"
PAD = 48


def _box_down(img, w2, h2):
    h, w = len(img), len(img[0])
    out = []
    for y in range(h2):
        y0, y1 = y * h // h2, (y + 1) * h // h2
        if y1 <= y0:
            y1 = y0 + 1
        row = []
        for x in range(w2):
            x0, x1 = x * w // w2, (x + 1) * w // w2
            if x1 <= x0:
                x1 = x0 + 1
            s = n = 0
            for yy in range(y0, min(y1, h)):
                r = img[yy]
                for xx in range(x0, min(x1, w)):
                    s += r[xx]
                    n += 1
            row.append(s // max(n, 1))
        out.append(row)
    return out


class Renderer:
    def __init__(self, face="Microsoft YaHei", size=24, mode="native",
                 sup=4, gamma=1.0, quality=G.ANTIALIASED_QUALITY):
        self.face, self.size, self.mode = face, size, mode
        self.sup, self.gamma = sup, gamma
        self.render_px = size * sup if mode == "super" else size
        self.pad = PAD
        self.cv = G.Canvas(face, self.render_px,
                           cw=self.render_px + PAD * 2, ch=self.render_px + PAD * 2,
                           quality=quality)
        self.win = None

    def _union(self):
        """参考字墨迹并集 -> 正方形窗口"""
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for ch in REF:
            A = self.cv.draw(ch, self.pad, self.pad)
            bb = G.ink_bbox(A, 20)
            if not bb:
                continue
            x0, y0 = min(x0, bb[0]), min(y0, bb[1])
            x1, y1 = max(x1, bb[2]), max(y1, bb[3])
        w, h = x1 - x0 + 1, y1 - y0 + 1
        side = int(max(w, h) * 1.04) + 1
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        self.win = (int(cx - side / 2), int(cy - side / 2), side)

    def glyph(self, ch):
        """返回 (w, h, rows)；native 模式为 1:1 原生像素"""
        if self.win is None:
            self._union()
        wx, wy, ws = self.win
        A = self.cv.draw(ch, self.pad, self.pad)
        bb = G.ink_bbox(A, 20)
        if bb is None:                       # 空白字（空格）
            ix0, iy0, ix1, iy1 = wx, wy, wx + ws - 1, wy + ws - 1
        else:
            ix0, iy0, ix1, iy1 = bb
        M = 1                                # 每边 1px 呼吸
        gx0 = max(min(wx, ix0 - M), 0)
        gy0 = max(min(wy, iy0 - M), 0)
        gx1 = min(max(wx + ws, ix1 + 1 + M), len(A[0]))
        gy1 = min(max(wy + ws, iy1 + 1 + M), len(A))
        gw, gh = gx1 - gx0, gy1 - gy0
        if self.mode == "super":
            W = max(1, round(self.size * gw / ws))
            H = max(1, round(self.size * gh / ws))
        else:
            W, H = gw, gh
        out = []
        for y in range(H):
            y0 = gy0 + y * gh // H
            y1 = max(y0 + 1, gy0 + (y + 1) * gh // H)
            row = []
            for x in range(W):
                x0 = gx0 + x * gw // W
                x1 = max(x0 + 1, gx0 + (x + 1) * gw // W)
                s = n = 0
                for yy in range(y0, min(y1, len(A))):
                    r = A[yy]
                    for xx in range(x0, min(x1, len(r))):
                        s += r[xx]
                        n += 1
                v = s // max(n, 1)
                if v < 10:
                    v = 0
                else:
                    v = min(255, int((v / 255.0) ** self.gamma * 255 + 0.5))
                row.append(v)
            out.append(row)
        return W, H, out


def load_chars(path):
    """读取用字表：纯文本，逐行/逐字符都接受，去重且保持顺序"""
    text = open(path, encoding="utf-8").read()
    seen, out = set(), []
    for ch in text:
        if ch in "\r\n\t ":
            continue
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chars", required=True, help="用字表（UTF-8 文本）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--face", default="Microsoft YaHei")
    ap.add_argument("--size", type=int, default=24)
    ap.add_argument("--mode", default="native", choices=["native", "super"])
    ap.add_argument("--gamma", type=float, default=0.95)
    ap.add_argument("--quality", type=int, default=G.ANTIALIASED_QUALITY)
    ap.add_argument("--charmap", default=None, help="charmap.json（提供码位分配）")
    a = ap.parse_args()

    chars = load_chars(a.chars)
    cmap = {}
    if a.charmap and os.path.exists(a.charmap):
        cmap = json.load(open(a.charmap, encoding="utf-8")).get("map", {})

    os.makedirs(a.out, exist_ok=True)
    r = Renderer(a.face, a.size, a.mode, 4, a.gamma, a.quality)
    print(f"渲染器 {a.face} {a.size}px mode={a.mode} gamma={a.gamma}  字数 {len(chars)}")

    index, skipped = [], []
    for ch in chars:
        try:
            w, h, rows = r.glyph(ch)
        except Exception as e:
            skipped.append((ch, str(e)))
            continue
        if w < 2 or h < 2:
            skipped.append((ch, "空字形"))
            continue
        code = int(cmap.get(ch, ord(ch)))
        name = f"{code}.pgm"
        FT.write_pgm(os.path.join(a.out, name), rows)
        index.append({"char": ch, "code": code, "file": name, "w": w, "h": h})

    json.dump(index, open(os.path.join(a.out, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"输出 {len(index)} 个字形 -> {a.out}/  (跳过 {len(skipped)})")
    for ch, why in skipped[:10]:
        print(f"  跳过 {ch!r}: {why}")


if __name__ == "__main__":
    main()
