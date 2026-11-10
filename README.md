# Ohgetsu Engine Toolkit

> 桜月（Ohgetsu）引擎逆向笔记与汉化工具集 —— 以《Silvery White ～君と出逢った理由～》(2006) 为样本整理。

一套可复用的工具和文档，用于处理这个 2006 年老引擎的常见汉化需求：脚本解包/回写、自绘字库（专用字库）、
EXE 补丁（标题本地化、全屏崩溃修复）、以及运行时行为追踪。

**本仓库不含任何游戏本体、剧本原文、译文、字库或图片资源**，只包含工具代码与格式文档。
使用前请自备正版游戏。

---

## 这个引擎的特点

| 项目 | 结论 |
|---|---|
| 引擎 | 桜月 / Ohgetsu，2006 年，x86 PE |
| 图形 | Direct3D 9，固定 800×600 |
| 输入 | DirectInput 8（独占，键盘注入无效） |
| 音频 | DSOUND + Ogg Vorbis（vorbis.dll / ogg.dll） |
| 归档 | `*.PAC`，容器索引写在 **EXE 内部**，条目为 LZSS 压缩 |
| 脚本 | 指令流 + 内联 Shift-JIS 文本，无长度字段 |
| 字体 | 启动时用 `GetGlyphOutlineA` 把 JIS 全字符集栅格化进 `font.bin`（1024×6144，BGRA） |
| 汉化难点 | 字库是**预生成纹理**，不是系统字体 → 必须自绘中文字形并写入字体图集 |

---

## 目录

```
docs/
  01-container-and-lzss.md    PAC 容器 + LZSS 压缩格式
  02-script-format.md         脚本指令流、文本条目、定长回写策略
  03-font-atlas-and-glyph.md  font.bin 图集布局 + 字形注入原理 + 自绘字库管线
  04-exe-patches.md           EXE 补丁：全屏崩溃修复（dmFields + 代码洞）、标题本地化
  05-runtime-tracing.md       D3D9 代理 / IAT 打点方法论、vtable 索引坑
  06-translation-pipeline.md  完整汉化流水线与工程经验

tools/
  lzss.py                LZSS 解压 / 压缩（纯 Python）
  script_tool.py         脚本解析、导出 JSON、译文本定长回写
  font_tool.py           font.bin 图集读写（导出字形 / 写入字形 / 生成预览图）
  gdirender.py           GDI 字形渲染画布（Windows）
  glyph_render.py        字形渲染管线：墨迹并集窗口 + 逐字扩窗 + 面积平均缩放
  make_charmap.py        码位分配（JIS 汉字池 / 保护集 / 标点复用）
  patch_exe.py           EXE 补丁工具（全屏修复 + 标题替换，幂等）
  d3d9_proxy.c           D3D9 诊断代理 DLL 源码（IAT 打点 + vtable 补丁）
  winmm_glyph_hook.c     字形注入 hook（winmm 代理 + GetGlyphOutlineA 拦截）
  winmm_fwd.def          winmm 全导出转发表
  Makefile               32 位 MinGW 构建脚本
```

---

## 快速上手

### 1. 解包脚本

容器索引在 EXE 里，先用现成工具（如 `OhgetsuPacArchiveTool`）解出条目，再用本仓库处理条目内部格式：

```bash
python tools/lzss.py d SCRIPT_0001.bin out_dec.bin      # LZS 条目 -> 原始脚本
python tools/script_tool.py parse out_dec.bin > entries.json
```

### 2. 回写译文

```bash
python tools/script_tool.py apply out_dec.bin trans.jsonl out_new.bin
# trans.jsonl 每行: {"off": 1234, "text": "中文译文"}
```

定长替换：译文 GBK 字节数不得超过原文 SJIS 字节数，余量补 `0x00`，后续指令偏移无需重算。

### 3. 生成专用字库

```bash
# 1) 分配码位
python tools/make_charmap.py used_chars.txt charmap.json

# 2) 渲染字形（Windows + 微软雅黑）
python tools/glyph_render.py --face "Microsoft YaHei" --size 24 --chars used_chars.txt --out glyphs/

# 3) 写入字体图集（或用 winmm hook 让游戏自己写，见 docs/03）
python tools/font_tool.py stamp font.bin glyphs/ out_font.bin
```

### 4. EXE 补丁

```bash
python tools/patch_exe.py fullscreen game.exe      # 修复高 DPI/高刷屏全屏崩溃
python tools/patch_exe.py title game.exe --title "SilveryWhite ～与你相遇的理由～"
```

---

## 关键结论速查

- **PAC 索引在 EXE 内**：`ExeEntry { u16 is_compressed; u16 resource_id; u32 offset; u32 length; }`，2048 字节对齐。
- **LZSS**：Okumura 经典实现，`N=4096`、`F=18`、初始填充 `0x20`、写指针从 `4078` 起，匹配长度 = 低 4 位 + 3。
- **脚本文本**：`AA 00 <u16 index>` + SJIS 文本 + `AB 00 00 00`，**没有长度字段** —— 读到非法字节为止。
- **字体图集**：1024×6144、32bpp BGRA、32×16 像素格、共 12288 槽、6 张 1024×1024 纹理。
- **字形注入**：`GetGlyphOutlineA` + `GGO_GRAY8_BITMAP(6)`，返回 8bit alpha，stride 4 字节对齐。
- **全屏崩溃**：`ChangeDisplaySettingsA` 传 `dmDisplayFrequency=0` + DPI 逻辑分辨率 → `DISP_CHANGE_BADMODE` → 隐藏窗口无限重试。
- **诊断利器**：app-local `d3d9.dll` 代理 + IAT 打点，比调试器好用得多（详见 `docs/05`）。

---

## 致谢与声明

- 引擎与游戏版权归 桜月 / 原作者 所有；本仓库仅用于技术研究与本地化学习，**不提供、不包含任何游戏资源**。
- 请支持正版。若权利人认为本仓库内容不妥，请联系删除。
- 工具代码以 MIT 协议发布，详见 `LICENSE`。

祝折腾愉快。
