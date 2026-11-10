# 05 · 运行时追踪：D3D9 代理与 IAT 打点

老游戏没有日志、没有符号，出问题只能靠猜。这一篇记录一套**不改游戏、可随时摘掉**的观测手段。

## 1. 为什么不用调试器

- 某些中文系统上 gdb/x64dbg attach 会因 Python 初始化/编码问题失败；
- 断点会改变时序，DirectInput 独占模式下游戏可能直接退出；
- 真正需要的信息往往只是"某个 API 被用什么参数调用了几次"。

`tools/d3d9_proxy.c` 是一个 **app-local DLL 代理**：把 `d3d9.dll` 放在游戏目录，
Windows 会优先加载它（同目录优先），我们即可在游戏进程内部做任何事。

## 2. 代理 DLL 的两条铁律

### 铁律一：导出名不能带修饰

用 MinGW 编译时，`__stdcall` 导出会变成 `Direct3DCreate9@4`，游戏会弹
「无法定位程序输入点 Direct3DCreate9 于动态链接库 …」。

```make
gcc -m32 -shared -O2 -nostartfiles -Wl,--kill-at -Wl,--entry,DllMain@12 \
    -o d3d9.dll d3d9_proxy.c
```

`--kill-at` 去掉 `@n`，导出名才是干净的 `Direct3DCreate9`。
用 `objdump -p d3d9.dll | grep -A20 "Export Address Table"` 验证。

### 铁律二：不要包整个 COM 对象

最初写了个完整 `IDirect3D9` 包装（30 多个方法转发），运行直接 `0xC0000005`。
后来的做法是 **vtable 槽位替换**：只改需要的几个槽，其余完全原样。

```c
void **vt = *(void ***)pD3D9;
DWORD old;
VirtualProtect(vt, sizeof(void *) * 10, PAGE_READWRITE, &old);   // 注意范围
vt[16] = my_CreateDevice;
VirtualProtect(vt, sizeof(void *) * 10, PAGE_EXECUTE_READ, &old);
```

### 坑：CreateDevice 的下标是 16，不是 15

`d3d9.h` 里 `IDirect3D9` 的 `CreateDevice` 按头文件数下来是第 15 个（0 起），
但**真实 vtable 是 16**。原因是 `QueryInterface/AddRef/Release` 之后还有
`RegisterSoftwareDevice`，头文件的接口继承顺序与实现不一致。

> 结论：**永远以实测为准**。用代理 DLL 遍历 vtable，打印每个槽指向的模块+偏移，
> 再和 `d3d9.dll` 的导出/符号对照，不要相信头文件的序号。

## 3. IAT 打点：观测任意 Win32 API

想记录 `user32!ShowWindow` / `ChangeDisplaySettingsA` 的调用，不用 hook 函数体，
改 IAT 指针即可（`tools/d3d9_proxy.c` 里的 `patch_iat`）：

```c
static void patch_iat(const char *dll, const char *fn, void *newfn) {
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    // 遍历 IMAGE_IMPORT_DESCRIPTOR -> 匹配 dll 名 -> 遍历 thunk -> 匹配函数名
    // VirtualProtect 后把 thunk 写成 newfn
}
```

比 IAT hook 更省事的还有 `d3d9.dll` 自带的 `Log()`：用 `wvsprintfA` 拼串再
`WriteFile` 追加，**不依赖 CRT**（`-nostartfiles` 下没有 `sprintf`/`malloc`）。

本项目的实战输出（节选）：

```
CreateDevice(800x600, fmt=22, 0x20) -> 0
ShowWindow(hwnd=0x001203A, cmd=0)
ChangeDisplaySettingsA(flags=0x4) 请求 800x600 32bpp 0Hz fields=0x005C0000 -> -2
ShowWindow(hwnd=0x001203A, cmd=0)
ChangeDisplaySettingsA(flags=0x4) 请求 800x600 32bpp 0Hz fields=0x005C0000 -> -2
...
```

一眼就能看出"进全屏失败后无限隐藏重试"，以及 DEVMODE 的具体内容。
全屏退出的那条则是 `1707x1067 fields=0x001C0000`，暴露了 DPI 逻辑分辨率问题。

## 4. 输入注入为什么经常无效

DirectInput 8 独占模式（`DISCL_EXCLUSIVE | DISCL_FOREGROUND`）下：

- `keybd_event` / `SendInput` / `PostMessage(WM_KEYDOWN)` 全部**不生效**；
- **鼠标点击有效**（鼠标走的光标路径不同，或游戏只是轮询 GetCursorPos/按键状态）。

所以自动化测试要么用鼠标点游戏自己的菜单，要么老老实实手按。
本项目所有全屏测试都是用**等比坐标点击**（按窗口 rect 的百分比算位置）完成的，
这样窗口尺寸变化（800×600 / 794×571）都不会点偏。

## 5. 机器环境也会"背锅"

排查前先确认这些，否则很容易误判成游戏 bug：

| 项 | 本例 |
|---|---|
| 缩放 | 2560×1600 @ 150%（游戏看到的桌面是 1707×1067） |
| 刷新率 | 240Hz（影响 `dmDisplayFrequency=0` 的兼容性） |
| 双显卡 | RTX 5070Ti Laptop + AMD iGPU（`GpuPreference` 会改变行为） |
| 兼容性标志 | `HIGHDPIAWARE` 等会改变窗口尺寸，测坐标前务必清空 |
| 崩溃转储 | `HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps` 可配置 |

## 6. 收尾

诊断完成后**务必删掉游戏目录下的 `d3d9.dll`**，否则会一直走代理路径；
`patch_iat` 只改进程内存，不影响磁盘文件，删了即恢复原状。
