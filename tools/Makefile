# 32 位 MinGW 构建脚本
#   make d3d9     诊断代理（放进游戏目录即可生效）
#   make winmm    字形注入 hook（需要先生成 cn_map.c，见下）
#
# cn_map.c 由 build_map 流程生成（tools/glyph_render.py 输出 + 转 C 数组），
# 格式:
#   const unsigned char cn_map_data[] = { <u32 count> <u16 code><u8 w><u8 h><w*h alpha>... };
#   const unsigned int  cn_map_count;
#
# -Wl,--kill-at 去掉 __stdcall 的 @n 修饰，否则导出名对不上，游戏会弹
# 「无法定位程序输入点」。

CC      ?= i686-w64-mingw32-gcc
CFLAGS  ?= -m32 -O2 -shared -nostartfiles -Wall
LDFLAGS ?= -Wl,--kill-at -Wl,--entry,DllMain@12

all: d3d9 winmm

d3d9: d3d9.dll

d3d9.dll: d3d9_proxy.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< -luser32 -lgdi32

winmm: winmm.dll

winmm.dll: winmm_glyph_hook.c cn_map.c winmm_fwd.def
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ winmm_glyph_hook.c cn_map.c winmm_fwd.def -luser32 -lgdi32

.PHONY: all d3d9 winmm clean
clean:
	rm -f d3d9.dll winmm.dll
