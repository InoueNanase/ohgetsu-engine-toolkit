# 03 · 字体图集与专用字库

这是整个汉化工程里最核心、也最容易翻车的部分。

## 1. 引擎的字体模型

游戏启动时**一次性**把 JIS 全字符集（约 8,800 个码位）用
`gdi32!GetGlyphOutlineA` 栅格化，结果写进 `font.bin`，运行期只从这张纹理里贴字。

也就是说：

- 游戏不读系统字体，**改系统字体没用**；
- 译文里的字必须事先"画"进 `font.bin`；
- 码位（字符编码）到图集槽位的映射由**游戏内部表**决定，我们只能复用现有码位。

## 2. font.bin 布局

| 项目 | 值 |
|---|---|
| 总尺寸 | 1024 × 6144 |
| 像素格式 | 32bpp BGRA（alpha 在第 4 字节） |
| 单元格 | 32 × 16 像素（宽 × 高） |
| 网格 | 每行 32 格，每张纹理 1024×1024 → 2048 格 |
| 纹理数 | 6 张（共 12288 个槽位） |
| 槽位换算 | `tex = idx // 2048`, `cx = (idx % 2048) % 32`, `cy = (idx % 2048) // 32` |

单元格内字形**垂直居中偏上**，宽度一般 23~25px（不是固定 32px），
所以字体图集里的字形是"每字一个 bbox"的稀疏贴图，不是等宽网格点阵。

> 实测游戏请求的字形黑盒约 23~25px，因此自绘源字形取 **24px**（原生抗锯齿）
> 或 26px 缩小到 24px 效果最佳，过小会断裂、过大会糊。

## 3. 字形注入（build-time hook）

思路：不自己算槽位，而是**骗过游戏**——让它在栅格化字形时拿到我们的位图，
它自己会把结果写进 `font.bin`。

实现方式：`winmm.dll` 代理（`tools/winmm_glyph_hook.c`）。

```
游戏 exe
  └─ 加载 winmm.dll（我们的代理）
       ├─ 192 个导出全部转发给系统 winmm_real.dll（少一个就加载失败）
       └─ DllMain: IAT 补丁 gdi32!GetGlyphOutlineA -> my_ggo
                     │
                     ├─ 保存 6 个参数 + 返回地址
                     ├─ 把栈上返回地址换成 post_handler
                     └─ 尾跳原函数（原函数 ret 后直接进 post_handler）
post_handler:
  ├─ 返回值 r = 原函数结果（GGO_GRAY8_BITMAP 时为写入的字节数，失败 -1）
  ├─ 若 uChar 命中我们的字形表：把缓冲区的位图替换成自绘字形（缩放 + 居中）
  └─ jmp 回原返回地址
```

**为什么要改写返回地址**：直接 `call` 原函数再 `jmp` 回去，需要自己平衡栈
（`ret 24` 的 stdcall 清理），而 MinGW 在 `call` 之后会生成 `sub esp` 而不是 `add esp`，
导致栈错位崩溃。改写返回地址可以让原函数自己 `ret 24`，栈由它清理，我们只做后处理。

关键细节：

- 只在 `(fuFormat & 0x0F) == 6`（`GGO_GRAY8_BITMAP`）时替换；
- `stride = (gmBlackBoxX + 3) & ~3`（4 字节对齐）；
- 目标区域先清零，再等比缩放居中；
- 尺寸一致时**直接 memcpy**，避免不必要的重采样；
- 不一致时用**面积平均**下采样（最近邻会造成笔画断裂）。

由于游戏会把结果落盘，**最终补丁不需要任何 DLL** —— hook 只是一次性生成工具。

## 4. 自绘字形渲染管线（`tools/glyph_render.py`）

要点是"窗口"的取法，而不是渲染 API：

1. **墨迹并集窗口**：先渲染一组参考字
   （`永国目田由甲申一丨丶口中日月目自明言高`），取墨迹并集的外接框，
   按 `max(w,h) * 1.04` 取正方形窗口。
   不能用「字身框」——雅黑这类字体的墨迹会超出字身框（尤其底部），直接裁会切掉笔画。
2. **逐字扩窗兜底**：单字如果墨迹超出该窗口，就把窗口向外扩到完全容纳墨迹（每边留 1px），
   这样长撇、长竖、繁体深字不会被截断。
3. **缩放**：`super` 模式 = 4 倍超采样后盒式下采样；`native` 模式 = 直接用
   `ANTIALIASED_QUALITY` 渲染到目标尺寸（更锐利，推荐）。
4. **gamma**：`v' = (v/255)^γ * 255`，γ < 1 加粗墨迹（雅黑在 24px 偏细），
   实践中 `γ = 0.95` 观感最好。

```bash
python tools/glyph_render.py --face "Microsoft YaHei" --size 24 \
    --mode native --gamma 0.95 --chars used_chars.txt --out glyphs/
```

输出 `glyphs/<码位>.pgm`（ASCII PGM，便于肉眼检查）+ `glyphs/index.json`。

## 5. 码位分配（`tools/make_charmap.py`）

图集槽位是有限的，必须复用日文码位：

| 规则 | 说明 |
|---|---|
| 分配池 | `0x889F .. 0xEAA4`（JIS 第一/第二水准汉字区，共 6398 个） |
| 保护集 | 约 63 个（角色名、菜单用字）保留日文字形，不参与分配 |
| ASCII | 直接用原码位（不占新槽） |
| 标点复用 | 「」『』、。！？等日文已有且形状一致的直接复用 |
| 其余 | 简体汉字、中文逗号等逐个分配新码位 |

实测 34,702 条对话用掉约 876 个码位，容量充足。

```bash
python tools/make_charmap.py used_chars.txt charmap.json
```

`charmap.json`：`{"map": {"你": 34975, ...}, "pool_start": 34975, "protected": [...]}`

## 6. 直接写图集（备选方案，`tools/font_tool.py`）

如果不想注入 DLL，也可以把渲染好的字形直接 stamp 进 `font.bin` 的槽位：

```bash
python tools/font_tool.py info  font.bin
python tools/font_tool.py dump  font.bin 34975 out.pgm
python tools/font_tool.py stamp font.bin glyphs/ out_font.bin --charmap charmap.json
python tools/font_tool.py sheet font.bin 34000 80 preview.png
```

`stamp` 会按 `charmap.json` 的码位 → 槽位关系写入，单元格内居中。
这条路更简单，但要注意：写进去的字形尺寸必须和游戏请求的黑盒接近，
否则显示时会二次缩放，边缘发虚。
