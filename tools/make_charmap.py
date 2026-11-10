# -*- coding: utf-8 -*-
"""码位分配 —— 决定每个汉字用哪个 JIS 码位（= 字体图集槽位）

规则（按优先级）:
  1. ASCII            -> 原码位（不占新槽）
  2. 保护集           -> 不分配，保留日文字形（角色名、菜单用字等）
  3. 能用 CP932 表示 -> 复用该码位（日文已有且形状一致：标点、部分汉字）
  4. 其余（简体汉字） -> 从分配池依次分配

分配池: 0x889F..0xEAA4（JIS 第一/第二水准汉字区，共 6398 个）

用法:
    python make_charmap.py used_chars.txt charmap.json [--protect protected.txt]
"""
import argparse
import json
import sys

POOL_START = 0x889F
POOL_END = 0xEAA4


def cp932_code(ch):
    """字符若可用 Shift-JIS 表示，返回其双字节码位（int），否则 None"""
    try:
        b = ch.encode("cp932")
    except UnicodeEncodeError:
        return None
    if len(b) == 2:
        return (b[0] << 8) | b[1]
    return None   # 单字节 ASCII 单独处理


def load_chars(path):
    text = open(path, encoding="utf-8").read()
    seen, out = set(), []
    for ch in text:
        if ch in "\r\n\t ":
            continue
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def build(chars, protected=(), redraw_all=False):
    protected = set(protected)
    pool_iter = POOL_START
    mapping, reused, skipped = {}, 0, []

    for ch in chars:
        if ch in protected:
            skipped.append(ch)
            continue
        if ord(ch) < 0x80:                      # ASCII
            mapping[ch] = ord(ch)
            continue
        code = cp932_code(ch)
        if code is not None and not redraw_all:  # 日文已有，直接复用
            mapping[ch] = code
            reused += 1
            continue
        # 从池里分配
        while pool_iter <= POOL_END and pool_iter in mapping.values():
            pool_iter += 1
        if pool_iter > POOL_END:
            raise SystemExit(f"码位池耗尽（需要 {len(chars)} 个）")
        mapping[ch] = pool_iter
        pool_iter += 1

    return {
        "map": mapping,
        "pool_start": POOL_START,
        "pool_end": POOL_END,
        "pool_used": sum(1 for v in mapping.values() if v >= POOL_START),
        "reused_cp932": reused,
        "protected": sorted(protected),
        "skipped": skipped,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chars")
    ap.add_argument("out")
    ap.add_argument("--protect", default=None, help="保护集（每行一个字，或用字表格式）")
    ap.add_argument("--redraw-all", action="store_true",
                    help="所有非 ASCII 字都重新分配码位（保证全套字形风格统一）")
    a = ap.parse_args()

    chars = load_chars(a.chars)
    prot = load_chars(a.protect) if a.protect else []
    cm = build(chars, prot, a.redraw_all)
    json.dump(cm, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"字符 {len(chars)}  分配 {len(cm['map'])}  "
          f"池内 {cm['pool_used']}  复用 CP932 {cm['reused_cp932']}  "
          f"保护/跳过 {len(cm['skipped'])}")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
