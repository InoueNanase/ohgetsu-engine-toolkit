# 04 · EXE 补丁

这个引擎的 EXE 没有任何 integrity check，可以放心改字节。下面两类补丁都做成了
**幂等**的：重复执行不会二次破坏，适合写进构建脚本。

`tools/patch_exe.py` 实现了全部补丁：

```bash
python tools/patch_exe.py title      game.exe --title "SilveryWhite ～与你相遇的理由～"
python tools/patch_exe.py fullscreen game.exe
python tools/patch_exe.py dump       game.exe          # 打印当前补丁状态
```

> 偏移基于《Silvery White》2006-09-29 版 `SilveryWhite.exe`（442,368 字节）。
> 换版本必须重新定位，脚本会校验目标字节，不匹配就拒绝修改。

---

## 1. 标题本地化（字符串替换）

标题在 EXE 里是 Shift-JIS 字符串 `SilveryWhite ～君と出逢った理由～`（33 字节），
共 7 处，其中 1 处嵌在退出确认串 `…を終了しますか？` 里。

中文系统按 CP936 解码 → 直接显示乱码。替换成 GBK 字节即可：

```
标题      6 处 -> "SilveryWhite ～与你相遇的理由～" (31 字节 + 2 个 0x00 填充)
退出确认   1 处 -> "确定要退出游戏吗？"
```

注意事项：

1. **必须先替换退出确认，再替换标题**。因为确认串包含标题，先替换标题会破坏确认串的匹配。
2. 新串**不能比原串长** —— 这些字符串在 rodata 里紧邻排列，越界会覆盖后面的数据。
3. 只用 ASCII + 全角字符时字节数可控；换成更长的中文标题要重新核算。

## 2. 全屏崩溃修复（两个独立缺陷）

### 症状

点「環境設定 → フルスクリーン」（或 Alt+Enter）后游戏"消失"：没有报错、没有托盘图标，
进程还活着但 CPU 占用为 0。

### 真相

游戏其实是死循环：`ShowWindow(hwnd, SW_HIDE)` + 无限重试 `ChangeDisplaySettingsA`。
用 D3D9 代理 IAT 打点（见 `05`）抓到的调用参数：

**缺陷 A（进不去）**

```
ChangeDisplaySettingsA(flags=0x4, dm.dmFields=0x005C0000, dm.dmDisplayFrequency=0)
  -> DISP_CHANGE_BADMODE (-2)
```

`dmFields` 包含 `DM_DISPLAYFREQUENCY`，但频率填 0。大多数老游戏能蒙混过关，
而高刷屏驱动（本机 RTX 5070Ti + 240Hz）会直接拒绝。

修复：把 `dmFields` 立即数 `0x005C0000 -> 0x001C0000`（去掉频率字段），
让驱动自己挑刷新率。

```
文件偏移 0x415C 和 0x4280:  00 00 5C 00  ->  00 00 1C 00
```

**缺陷 B（退不出来）**

游戏是 DPI-unaware 进程，保存的"桌面分辨率"是 **DPI 逻辑值 1707×1067**
（物理 2560×1600，150% 缩放）。退出全屏时拿这个不存在的模式去恢复 → 同样 BADMODE →
同样的隐藏+重试死循环。

修复思路：让恢复调用改走 `ChangeDisplaySettingsA(NULL, 0)` —— 恢复注册表默认模式，
与 DPI 缩放完全无关。

但 `push eax`（1 字节 `50`）改成 `push 0`（`6A 00`）会多出 1 字节，**不能原地替换**。
解决办法是**代码洞 + 跳转**：

```
原代码（7 字节）：  50 FF 15 34 52 43 00      push eax; call [__imp_ChangeDisplaySettingsA]
改成：              E9 <rel32> 90 90           jmp cave; nop nop

代码洞（13 字节）：
  6A 00                 push 0
  FF 15 34 52 43 00     call [__imp_ChangeDisplaySettingsA]
  E9 <rel32>            jmp back（回到原 call 的下一条指令）
```

两处恢复调用点 + 两处代码洞：

| 项目 | 文件偏移 | VA |
|---|---|---|
| 调用点 1 | `0x23853` | `0x423853` |
| 调用点 2 | `0x2447A` | `0x42447A` |
| 代码洞 1 | `0x34460` | `0x434460` |
| 代码洞 2 | `0x34470` | `0x434470` |

代码洞用的是 `.text` 节尾部的 slack（`SizeOfRawData - VirtualSize`，本 EXE 有 2987 字节），
全零、不会被任何代码执行到，是天然的 cave。

> 进入全屏的调用点（`0x23A4D`，`push 4; lea edx, [ebp-0xA0]`，`CDS_FULLSCREEN`）
> **不要动** —— 它需要真实的 DEVMODE。

### 不要用 DPI 感知兼容标志

给 exe 加 `HIGHDPIAWARE` 兼容标志看似能解决，实际会让游戏按 `96/DPI` 自行缩放，
窗口直接缩成 537×427，点击坐标全错。**放弃这条路**。

## 3. 补丁的工程化

`rebuild.py`（本项目私有）里的做法值得借鉴：

- 补丁函数**只改打包产物**，`_backup_orig` 永远是原版，随时可回滚；
- 每个补丁先校验目标字节，命中才写，重复执行无副作用；
- 顺序有依赖时（标题 vs 退出确认）在函数内注释说明；
- 打完补丁打印命中数量，构建日志里能直接看出是否生效。

## 4. 校验

改完 EXE 后，最快的功能验证不是肉眼看：直接读窗口标题。

```python
import ctypes
u = ctypes.windll.user32
buf = ctypes.create_string_buffer(256)
u.GetWindowTextA(hwnd, buf, 256)
print(buf.raw.split(b"\x00")[0].decode("gbk"))
```

全屏则用 `GetWindowRect` + `GetSystemMetrics(0)` 对拍：

```
进全屏: 窗口 (0,0,800,600)，桌面 800x600，IsWindowVisible = True
退全屏: 窗口恢复原尺寸，桌面恢复原分辨率，IsWindowVisible = True
```

如果 `IsWindowVisible` 变 False 而进程还活着 —— 就是本文档描述的死循环。
