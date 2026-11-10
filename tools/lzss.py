# -*- coding: utf-8 -*-
"""LZSS (Okumura) 解压 / 压缩 —— 桜月引擎 PAC 条目内部格式

条目格式:
    "LZS\\0" + uint32 解压后大小(LE) + LZSS 流

参数:
    N = 4096     环形缓冲区
    F = 18       最大匹配长度
    初始填充 0x20, 写指针从 4078 开始
    标志字节 8 个 token, 低位优先: 1=字面量, 0=匹配
    匹配: 12-bit 绝对环形位置 + 4-bit (长度-3)
"""
import struct
import sys

N = 4096
F = 18
MIN_MATCH = 3
MAGIC = b"LZS\x00"


def decompress(data: bytes, out_size: int) -> bytes:
    """解码 LZSS 流（不含 LZS 头）"""
    buf = bytearray([0x20]) * N
    r = N - F
    out = bytearray()
    i, n = 0, len(data)
    while len(out) < out_size and i < n:
        flags = data[i]
        i += 1
        for _ in range(8):
            if len(out) >= out_size or i >= n:
                break
            if flags & 1:                       # 字面量
                c = data[i]
                i += 1
                out.append(c)
                buf[r] = c
                r = (r + 1) & (N - 1)
            else:                                # 匹配
                if i + 1 >= n:
                    break
                b1, b2 = data[i], data[i + 1]
                i += 2
                pos = b1 | ((b2 & 0xF0) << 4)    # 绝对环形位置
                ln = (b2 & 0x0F) + MIN_MATCH
                for k in range(ln):
                    c = buf[(pos + k) & (N - 1)]
                    out.append(c)
                    buf[r] = c
                    r = (r + 1) & (N - 1)
            flags >>= 1
    return bytes(out)


def decompress_entry(raw: bytes) -> tuple:
    """解码整条 PAC 条目，返回 (data, was_compressed)"""
    if raw[:4] != MAGIC:
        return raw, False
    size = struct.unpack("<I", raw[4:8])[0]
    return decompress(raw[8:], size), True


def compress(data: bytes, max_candidates: int = 64) -> bytes:
    """编码为 LZSS 流（不含 LZS 头）

    用 3 字节前缀索引找候选，再逐字节验证最长匹配。
    输出不保证与原厂压缩流逐字节相同，但解码结果等价。
    """
    n = len(data)
    out = bytearray()
    table = {}                    # 3-byte key -> [positions]
    i = 0

    def remember(p):
        if p + 3 <= n:
            key = data[p:p + 3]
            lst = table.get(key)
            if lst is None:
                table[key] = [p]
            else:
                lst.append(p)
                if len(lst) > max_candidates:
                    del lst[0]

    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len, best_pos = 0, 0
            if i + MIN_MATCH <= n:
                cands = table.get(data[i:i + 3])
                if cands:
                    limit = min(F, n - i)
                    for q in reversed(cands):
                        if i - q > N - 1:          # 超出窗口
                            break
                        ln = 3
                        while ln < limit and data[q + ln] == data[i + ln]:
                            ln += 1
                        if ln > best_len:
                            best_len, best_pos = ln, q
                            if ln >= limit:
                                break
            if best_len >= MIN_MATCH:
                # 解码端写指针从 4078 起步，位置编码必须加上这个偏移
                pos = (best_pos + (N - F)) & (N - 1)
                out.append(pos & 0xFF)
                out.append(((pos >> 4) & 0xF0) | (best_len - MIN_MATCH))
                for k in range(best_len):
                    remember(i + k)
                i += best_len
            else:
                out.append(data[i])
                remember(i)
                i += 1
                flags |= 1 << bit
        out[flag_pos] = flags
    return bytes(out)


def compress_entry(data: bytes) -> bytes:
    """打包成完整 PAC 条目（LZS 头 + 流）"""
    return MAGIC + struct.pack("<I", len(data)) + compress(data)


def _selftest():
    import os
    ok = 0
    samples = [
        b"",
        b"A",
        b"A" * 5000,
        bytes(range(256)) * 20,
        (b"the quick brown fox jumps over the lazy dog. " * 100),
        os.urandom(4096),
        b"\x00" * 20000,
    ]
    for s in samples:
        enc = compress(s)
        dec = decompress(enc, len(s))
        assert dec == s, f"round-trip 失败: len={len(s)}"
        ok += 1
    # 边界: 恰好 4096 / F 长度
    for ln in (4095, 4096, 4097, 17, 18, 19):
        s = bytes((i * 7 + 3) & 0xFF for i in range(ln))
        assert decompress(compress(s), ln) == s, ln
        ok += 1
    print(f"自检通过 ({ok} 组样本)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法:")
        print("  python lzss.py d <in.lzs> <out.bin>   解压")
        print("  python lzss.py c <in.bin> <out.lzs>   压缩")
        print("  python lzss.py t                      自检")
        return
    cmd = sys.argv[1]
    if cmd == "t":
        _selftest()
        return
    src, dst = sys.argv[2], sys.argv[3]
    raw = open(src, "rb").read()
    if cmd == "d":
        data, was = decompress_entry(raw)
        open(dst, "wb").write(data)
        print(f"解压 {len(raw):,} -> {len(data):,} 字节"
              f"{'（未压缩条目）' if not was else ''}")
    elif cmd == "c":
        enc = compress_entry(raw)
        open(dst, "wb").write(enc)
        print(f"压缩 {len(raw):,} -> {len(enc):,} 字节 "
              f"({len(enc) / max(len(raw), 1) * 100:.1f}%)")
    else:
        print("未知命令:", cmd)


if __name__ == "__main__":
    main()
