# -*- coding: utf-8 -*-
"""font.bin 字体图集工具 —— 查看 / 导出字形 / 写入字形 / 生成预览

图集布局:
    1024 x 6144, 32bpp BGRA, alpha 在第 4 字节
    单元格 32 x 16 像素, 每行 32 格
    6 张 1024x1024 纹理, 共 12288 槽
    tex = idx // 2048, cx = (idx % 2048) % 32, cy = (idx % 2048) // 32

用法:
    python font_tool.py info  <font.bin>
    python font_tool.py dump  <font.bin> <slot> <out.pgm>
    python font_tool.py sheet <font.bin> <start_slot> <count> <out.png>
    python font_tool.py stamp <font.bin> <glyphs/index.json> <out.bin> [slots.json]

slots.json（可选）: {"34975": 1203}  码位 -> 槽位；缺省视为相等
"""
import json
import os
import struct
import sys
import zlib

W = 1024
CELL_W, CELL_H = 32, 16
COLS = W // CELL_W          # 32
TEX_H = 1024
SLOTS_PER_TEX = (W // CELL_W) * (TEX_H // CELL_H)   # 2048
TOTAL_SLOTS = SLOTS_PER_TEX * 6                     # 12288
FILE_SIZE = W * TEX_H * 6 * 4                       # 25,165,824


def slot_origin(idx: int):
    """槽位 -> 图集左上角像素坐标"""
    tex = idx // SLOTS_PER_TEX
    off = idx % SLOTS_PER_TEX
    cx, cy = off % COLS, off // COLS
    return cx * CELL_W, tex * TEX_H + cy * CELL_H


def read_cell(d: bytes, idx: int, cw=CELL_W, ch=CELL_H):
    """读出一格的 alpha 灰度（返回 rows[y][x]）"""
    ox, oy = slot_origin(idx)
    rows = []
    for y in range(ch):
        row = []
        base = ((oy + y) * W + ox) * 4
        for x in range(cw):
            row.append(d[base + x * 4 + 3] if base + x * 4 + 3 < len(d) else 0)
        rows.append(row)
    return rows


def write_cell(d: bytearray, idx: int, mask, valign=1):
    """把掩码写入一格（清空后居中）"""
    ox, oy = slot_origin(idx)
    for y in range(CELL_H):
        for x in range(CELL_W):
            p = ((oy + y) * W + ox + x) * 4
            d[p] = d[p + 1] = d[p + 2] = 255
            d[p + 3] = 0
    h, w = len(mask), len(mask[0])
    if w > CELL_W or h > CELL_H:
        raise ValueError(f"字形 {w}x{h} 超出单元格 {CELL_W}x{CELL_H}")
    dx = max(0, (CELL_W - w) // 2)
    dy = valign if h + valign <= CELL_H else max(0, CELL_H - h)
    for y in range(h):
        for x in range(w):
            p = ((oy + dy + y) * W + ox + dx + x) * 4
            d[p] = d[p + 1] = d[p + 2] = 255
            d[p + 3] = mask[y][x]


# ---------- PGM / PNG ----------

def read_pgm(path):
    data = open(path, "rb").read()
    if not data.startswith(b"P5"):
        raise ValueError("仅支持 P5 二进制 PGM")
    fields, i = [], 2
    while len(fields) < 3:
        while i < len(data) and data[i] in b" \t\r\n":
            i += 1
        if data[i:i + 1] == b"#":
            while i < len(data) and data[i] not in b"\r\n":
                i += 1
            continue
        j = i
        while j < len(data) and data[j] not in b" \t\r\n":
            j += 1
        fields.append(int(data[i:j]))
        i = j
    w, h, _ = fields
    i += 1
    px = data[i:i + w * h]
    return w, h, [list(px[y * w:(y + 1) * w]) for y in range(h)]


def write_pgm(path, rows):
    h, w = len(rows), len(rows[0])
    with open(path, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        f.write(bytes(v for row in rows for v in row))


def write_png(path, rows, scale=1):
    h, w = len(rows), len(rows[0])
    if scale > 1:
        rows = [[v for v in row for _ in range(scale)] for row in rows for _ in range(scale)]
        h, w = h * scale, w * scale
    raw = b"".join(b"\x00" + bytes(row) for row in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


# ---------- 命令 ----------

def cmd_info(path):
    size = os.path.getsize(path)
    print(f"{path}: {size:,} 字节")
    print(f"  图集 {W}x{TEX_H * 6}  单元格 {CELL_W}x{CELL_H}  槽位 {TOTAL_SLOTS}")
    if size != FILE_SIZE:
        print(f"  !! 大小与预期 {FILE_SIZE:,} 不符（可能是别的版本或未生成完）")
    d = open(path, "rb").read()
    filled = 0
    for idx in range(0, TOTAL_SLOTS, 37):          # 抽样
        rows = read_cell(d, idx)
        if any(any(r) for r in rows):
            filled += 1
    print(f"  抽样填充率 ≈ {filled / (TOTAL_SLOTS // 37 + 1) * 100:.1f}%")


def cmd_dump(path, idx, out):
    d = open(path, "rb").read()
    rows = read_cell(d, int(idx))
    write_png(out, rows, scale=4)
    print(f"槽位 {idx} -> {out} (放大 4x)")


def cmd_sheet(path, start, count, out, scale=2):
    d = open(path, "rb").read()
    start, count = int(start), int(count)
    cols = 16
    rows_n = (count + cols - 1) // cols
    sheet = []
    for ry in range(rows_n):
        for y in range(CELL_H):
            row = []
            for rx in range(cols):
                idx = start + ry * cols + rx
                cell = read_cell(d, idx) if idx < TOTAL_SLOTS else [[0] * CELL_W] * CELL_H
                row.extend(cell[y])
            sheet.append(row)
    write_png(out, sheet, scale=scale)
    print(f"槽位 {start}..{start + count - 1} -> {out} ({cols} 列)")


def cmd_stamp(font_in, index_json, font_out, slots_json=None):
    d = bytearray(open(font_in, "rb").read())
    idx = json.load(open(index_json, encoding="utf-8"))
    slots = {}
    if slots_json and os.path.exists(slots_json):
        slots = {int(k): int(v) for k, v in json.load(open(slots_json)).items()}
    n = 0
    for rec in idx:
        code = int(rec["code"])
        slot = slots.get(code, code)
        if slot >= TOTAL_SLOTS:
            print(f"  跳过 {rec['char']}: 槽位 {slot} 越界")
            continue
        w, h, rows = read_pgm(os.path.join(os.path.dirname(index_json), rec["file"]))
        write_cell(d, slot, rows)
        n += 1
    open(font_out, "wb").write(d)
    print(f"写入 {n} 个字形 -> {font_out}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "info":
        cmd_info(sys.argv[2])
    elif cmd == "dump":
        cmd_dump(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "sheet":
        cmd_sheet(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "stamp":
        cmd_stamp(*sys.argv[2:6])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
