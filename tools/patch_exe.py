# -*- coding: utf-8 -*-
"""桜月引擎 EXE 补丁工具（幂等）

子命令:
    status      <exe>                              查看补丁状态
    title       <exe> [--title 文本] [--confirm 文本]   标题/退出确认本地化
    fullscreen  <exe>                              修复高 DPI / 高刷屏下全屏崩溃

偏移基于《Silvery White》2006-09-29 版 SilveryWhite.exe（442,368 字节）。
脚本会校验目标字节，不匹配直接报错，不会盲改。

全屏修复原理见 docs/04-exe-patches.md。
"""
import argparse
import os
import struct
import sys

# ---------- 标题 ----------
TITLE_OLD = (b"SilveryWhite \x81\x60\x8cN\x82\xc6\x8fo\x88\xa7"
             b"\x82\xc1\x82\xbd\x97\x9d\x97R\x81\x60")          # 33 字节 SJIS
CONFIRM_SUFFIX = b" \x82\xf0\x8fI\x97\xb9\x82\xb5\x82\xdc\x82\xb7\x82\xa9\x81H"
TITLE_DEFAULT = "SilveryWhite ～与你相遇的理由～"
CONFIRM_DEFAULT = "确定要退出游戏吗？"

# ---------- 全屏 ----------
DMFIELD_OFFS = (0x415C, 0x4280)
DMFIELD_OLD = bytes.fromhex("00005C00")     # DM_BITSPERPEL|DM_PELSWIDTH|DM_PELSHEIGHT|DM_DISPLAYFREQUENCY
DMFIELD_NEW = bytes.fromhex("00001C00")     # 去掉 DM_DISPLAYFREQUENCY
CDSA_IAT = 0x435234                          # __imp__ChangeDisplaySettingsA
SITES = (0x23853, 0x2447A)                   # push eax; call [CDSA]
SEQ = bytes.fromhex("50ff1534524300")
CAVE_OFF = 0x34460                           # .text 尾部 slack
EXPECT_SIZE = 442368


def load(path):
    d = bytearray(open(path, "rb").read())
    if len(d) != EXPECT_SIZE:
        print(f"!! 文件大小 {len(d):,} != 预期 {EXPECT_SIZE:,}，偏移可能不适用")
        print("   如确认是同一构建，可加 --force 继续（风险自负）")
    return d


def va_of(off, imagebase=0x400000, text_va=0x1000, text_raw=0x1000):
    return imagebase + text_va + (off - text_raw)


def cmd_status(path):
    d = bytes(open(path, "rb").read())
    print(f"{path}: {len(d):,} 字节")
    dm = all(d[o:o + 4] == DMFIELD_NEW for o in DMFIELD_OFFS)
    dm_old = all(d[o:o + 4] == DMFIELD_OLD for o in DMFIELD_OFFS)
    print(f"  dmFields 全屏补丁: {'已打' if dm else ('未打' if dm_old else '状态异常')}")
    st = []
    for o in SITES:
        if bytes(d[o:o + 7]) == SEQ:
            st.append("未打")
        elif d[o] == 0xE9:
            st.append("已打")
        else:
            st.append("异常")
    print(f"  恢复调用点: {', '.join(f'{o:#x}={s}' for o, s in zip(SITES, st))}")
    print(f"  标题(中文 GBK): {d.count(TITLE_DEFAULT.encode('gbk'))} 处")
    print(f"  标题(日文 SJIS): {d.count(TITLE_OLD)} 处")


def cmd_title(path, title, confirm, force=False):
    d = load(path)
    if not force and len(d) != EXPECT_SIZE:
        sys.exit("大小不符，已中止（--force 可强制）")
    try:
        new_title = title.encode("gbk")
        new_confirm = confirm.encode("gbk")
    except UnicodeEncodeError as e:
        sys.exit(f"文本无法用 GBK 编码: {e}")
    if len(new_title) > len(TITLE_OLD):
        sys.exit(f"标题过长: {len(new_title)} > {len(TITLE_OLD)} 字节")

    # 先打退出确认（其中包含标题，顺序反了会破坏匹配）
    old_confirm = TITLE_OLD + CONFIRM_SUFFIX
    n2 = 0
    i = d.find(old_confirm)
    while i != -1:
        d[i:i + len(old_confirm)] = new_confirm + b"\x00" * (len(old_confirm) - len(new_confirm))
        n2 += 1
        i = d.find(old_confirm, i + len(old_confirm))
    # 再打标题
    n1 = 0
    i = d.find(TITLE_OLD)
    while i != -1:
        d[i:i + len(TITLE_OLD)] = new_title + b"\x00" * (len(TITLE_OLD) - len(new_title))
        n1 += 1
        i = d.find(TITLE_OLD, i + len(TITLE_OLD))

    if n1 == 0 and n2 == 0:
        print("未找到原文串（可能已打过补丁）")
        return
    open(path, "wb").write(d)
    print(f"标题 {n1} 处 / 退出确认 {n2} 处 已本地化 -> {path}")


def cmd_fullscreen(path, force=False):
    d = load(path)
    if not force and len(d) != EXPECT_SIZE:
        sys.exit("大小不符，已中止（--force 可强制）")

    # 1) dmFields
    changed = 0
    for o in DMFIELD_OFFS:
        if bytes(d[o:o + 4]) == DMFIELD_OLD:
            d[o:o + 4] = DMFIELD_NEW
            changed += 1
        elif bytes(d[o:o + 4]) != DMFIELD_NEW:
            sys.exit(f"!! dmFields 偏移 {o:#x} 字节不匹配，拒绝修改")

    # 2) 恢复路径代码洞
    applied = 0
    for i, off in enumerate(SITES):
        if bytes(d[off:off + 7]) == SEQ:
            site_va = va_of(off)
            cave_va = va_of(CAVE_OFF + i * 16)
            code = bytes.fromhex("6a00")                                  # push 0
            code += bytes.fromhex("ff15") + struct.pack("<I", CDSA_IAT)    # call [CDSA]
            rel = (site_va + 7) - (cave_va + len(code) + 5)
            code += b"\xE9" + struct.pack("<i", rel)                       # jmp back
            d[CAVE_OFF + i * 16: CAVE_OFF + i * 16 + len(code)] = code
            d[off:off + 7] = b"\xE9" + struct.pack("<i", cave_va - (site_va + 5)) + b"\x90\x90"
            applied += 1
        elif d[off] == 0xE9:
            pass
        else:
            sys.exit(f"!! 调用点 {off:#x} 字节不匹配，拒绝修改")

    open(path, "wb").write(d)
    print(f"全屏修复: dmFields {changed} 处, 代码洞 {applied} 处 -> {path}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status"); s.add_argument("exe")

    s = sub.add_parser("title")
    s.add_argument("exe")
    s.add_argument("--title", default=TITLE_DEFAULT)
    s.add_argument("--confirm", default=CONFIRM_DEFAULT)
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("fullscreen")
    s.add_argument("exe")
    s.add_argument("--force", action="store_true")

    a = ap.parse_args()
    if a.cmd == "status":
        cmd_status(a.exe)
    elif a.cmd == "title":
        cmd_title(a.exe, a.title, a.confirm, a.force)
    elif a.cmd == "fullscreen":
        cmd_fullscreen(a.exe, a.force)


if __name__ == "__main__":
    main()
