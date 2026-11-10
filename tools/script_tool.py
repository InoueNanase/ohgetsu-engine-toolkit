# -*- coding: utf-8 -*-
"""桜月引擎脚本工具 —— 解析 / 导出 / 定长回写

解压后的脚本是「指令流 + 内联文本」：

    指令 (4 字节): [u8 opcode][u24 param]
    文本条目    : AA 00 <index:u16 le> + Shift-JIS 文本 + [00 00] + AB 00 00 00

文本没有长度字段，只能读到第一个非法 Shift-JIS 字节为止。

用法:
    python script_tool.py parse  <script_dec.bin> [out.json]      解析
    python script_tool.py apply  <script_dec.bin> <trans.jsonl> <out.bin>
    python script_tool.py verify <src.bin> <dst.bin>              回写后校验

trans.jsonl 每行:
    {"off": 1238, "text": "中文译文"}
    off 为 script_tool.py parse 输出的 text_off
"""
import json
import sys

AA, AB = 0xAA, 0xAB

OPCODES = {
    0xA0: "text?", 0xA1: "cmd", 0xA2: "cmd", 0xA3: "cmd", 0xA4: "cmd",
    0xA8: "cmd", 0xAA: "text", 0xAB: "end", 0xAC: "cmd", 0xAD: "cmd",
}


def is_sjis_lead(c: int) -> bool:
    return 0x81 <= c <= 0x9F or 0xE0 <= c <= 0xEF


def is_sjis_pair(c1: int, c2: int) -> bool:
    return is_sjis_lead(c1) and (0x40 <= c2 <= 0x7E or 0x80 <= c2 <= 0xFC)


def read_text(buf: bytearray, p: int):
    """从 p 读 SJIS 文本，返回 (text_bytes, end_offset)"""
    start, n = p, len(buf)
    while p < n:
        c = buf[p]
        if c == 0:
            break
        if p + 1 < n and is_sjis_pair(c, buf[p + 1]):
            p += 2
            continue
        if 0x20 <= c < 0x7F:
            p += 1
            continue
        break
    return bytes(buf[start:p]), p


def parse(buf: bytearray):
    """扫描全部文本条目"""
    entries, n, i = [], len(buf), 0
    while i < n - 4:
        if buf[i] == AA and buf[i + 1] == 0x00:
            index = buf[i + 2] | (buf[i + 3] << 8)
            text, end = read_text(buf, i + 4)
            if text:
                tail = 0
                if end + 1 < n and buf[end] == 0 and buf[end + 1] == 0:
                    tail = 2
                entries.append({
                    "index": index,
                    "hdr_off": i,
                    "text_off": i + 4,
                    "text_len": len(text),
                    "tail": tail,
                    "sjis": text.decode("cp932", "replace"),
                    "raw_hex": text.hex(),
                })
                i = end
                continue
        i += 1
    return entries


def apply_translations(buf: bytearray, trans: dict) -> tuple:
    """定长回写。trans: {text_off: 译文}

    返回 (命中数, 跳过列表)。译文 GBK 长度超过原文字节数时跳过（不截断）。
    """
    entries = parse(buf)
    by_off = {e["text_off"]: e for e in entries}
    done, skipped = 0, []
    for off, text in trans.items():
        e = by_off.get(off)
        if e is None:
            skipped.append((off, "偏移未命中"))
            continue
        try:
            enc = text.encode("gbk")
        except UnicodeEncodeError as ex:
            skipped.append((off, f"GBK 不可编码: {ex}"))
            continue
        if len(enc) > e["text_len"]:
            skipped.append((off, f"超长 {len(enc)} > {e['text_len']}"))
            continue
        start = e["text_off"]
        buf[start:start + e["text_len"]] = enc + b"\x00" * (e["text_len"] - len(enc))
        done += 1
    return done, skipped


def _load_trans(path: str) -> dict:
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        out[int(r["off"])] = r["text"]
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]

    if cmd == "parse":
        src = sys.argv[2]
        out = sys.argv[3] if len(sys.argv) > 3 else None
        buf = bytearray(open(src, "rb").read())
        ents = parse(buf)
        chars = sum(len(e["sjis"]) for e in ents)
        print(f"{src}: {len(buf):,} 字节  条目 {len(ents):,}  字符 {chars:,}")
        if out:
            json.dump(ents, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"-> {out}")

    elif cmd == "apply":
        src, trans_path, dst = sys.argv[2], sys.argv[3], sys.argv[4]
        buf = bytearray(open(src, "rb").read())
        trans = _load_trans(trans_path)
        done, skipped = apply_translations(buf, trans)
        open(dst, "wb").write(buf)
        print(f"回写 {done}/{len(trans)} 条 -> {dst}（长度不变: {len(buf):,}）")
        for off, why in skipped[:20]:
            print(f"  跳过 off={off}: {why}")
        if len(skipped) > 20:
            print(f"  ... 共 {len(skipped)} 条跳过")

    elif cmd == "verify":
        a, b = bytearray(open(sys.argv[2], "rb").read()), bytearray(open(sys.argv[3], "rb").read())
        if len(a) != len(b):
            print(f"!! 长度不一致: {len(a):,} vs {len(b):,}")
            return
        ea, eb = parse(a), parse(b)
        print(f"条目数 {len(ea)} vs {len(eb)}")
        bad = [(x['text_off'], y['text_off']) for x, y in zip(ea, eb)
               if x["text_off"] != y["text_off"] or x["text_len"] != y["text_len"]]
        print("结构一致" if not bad else f"!! {len(bad)} 条结构变化: {bad[:5]}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
