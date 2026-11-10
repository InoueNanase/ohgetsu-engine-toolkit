/* d3d9 诊断代理 v4：D3D9 CreateDevice 日志 + user32 窗口/显示 API 的 IAT 日志
 * 构建：gcc -shared -O2 -nostartfiles -Wl,--kill-at -Wl,--entry,DllMain@12
 */
#include <windows.h>
#include <d3d9.h>
#include <stdarg.h>

static HMODULE g_real;
static IDirect3D9 * (WINAPI *pDirect3DCreate9)(UINT);

/* ---------------- 日志 ---------------- */
static void log_path(char *out, DWORD n)
{
    static char cached[MAX_PATH];
    if (!cached[0]) {
        HMODULE self = NULL;
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)log_path, &self);
        GetModuleFileNameA(self, cached, MAX_PATH);
        char *slash = cached, *p;
        for (p = cached; *p; p++) if (*p == '\\') slash = p;
        lstrcpyA(slash + 1, "d3d9_proxy.log");
    }
    lstrcpynA(out, cached, n);
}

static void logf_(const char *fmt, ...)
{
    char buf[1024], path[MAX_PATH];
    va_list ap;
    va_start(ap, fmt);
    wvsprintfA(buf, fmt, ap);
    va_end(ap);
    log_path(path, MAX_PATH);
    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD n = lstrlenA(buf);
    buf[n++] = '\r'; buf[n++] = '\n';
    DWORD w;
    SetFilePointer(h, 0, NULL, FILE_END);
    WriteFile(h, buf, n, &w, NULL);
    CloseHandle(h);
}

/* ---------------- user32 钩子 ---------------- */
static BOOL  (WINAPI *o_ShowWindow)(HWND, int);
static BOOL  (WINAPI *o_SetWindowPos)(HWND, HWND, int, int, int, int, UINT);
static HWND  (WINAPI *o_CreateWindowExA)(DWORD, LPCSTR, LPCSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
static LONG  (WINAPI *o_ChangeDisplaySettingsA)(void *, DWORD);
static BOOL  (WINAPI *o_MoveWindow)(HWND, int, int, int, int, BOOL);
static LONG  (WINAPI *o_SetWindowLongA)(HWND, int, LONG);
static BOOL  (WINAPI *o_SetWindowTextA)(HWND, LPCSTR);

static BOOL WINAPI h_ShowWindow(HWND h, int cmd)
{
    BOOL r = o_ShowWindow(h, cmd);
    logf_("ShowWindow(hwnd=%08X cmd=%d) -> %d", (DWORD)h, cmd, r);
    return r;
}
static BOOL WINAPI h_SetWindowPos(HWND h, HWND after, int x, int y, int cx, int cy, UINT flags)
{
    BOOL r = o_SetWindowPos(h, after, x, y, cx, cy, flags);
    logf_("SetWindowPos(%08X x=%d y=%d cx=%d cy=%d flags=0x%X) -> %d", (DWORD)h, x, y, cx, cy, flags, r);
    return r;
}
static HWND WINAPI h_CreateWindowExA(DWORD ex, LPCSTR cls, LPCSTR title, DWORD style,
                                     int x, int y, int cx, int cy, HWND parent, HMENU menu, HINSTANCE inst, LPVOID param)
{
    HWND r = o_CreateWindowExA(ex, cls, title, style, x, y, cx, cy, parent, menu, inst, param);
    logf_("CreateWindowExA(cls=%s style=0x%08X %dx%d at %d,%d) -> %08X", cls ? cls : "?", style, cx, cy, x, y, (DWORD)r);
    return r;
}
static LONG WINAPI h_ChangeDisplaySettingsA(void *devmode, DWORD flags)
{
    LONG r = o_ChangeDisplaySettingsA(devmode, flags);
    logf_("ChangeDisplaySettingsA(flags=0x%X) -> %ld", flags, r);
    return r;
}
static BOOL WINAPI h_MoveWindow(HWND h, int x, int y, int cx, int cy, BOOL repaint)
{
    BOOL r = o_MoveWindow(h, x, y, cx, cy, repaint);
    logf_("MoveWindow(%08X %d,%d %dx%d) -> %d", (DWORD)h, x, y, cx, cy, r);
    return r;
}
static LONG WINAPI h_SetWindowLongA(HWND h, int idx, LONG val)
{
    LONG r = o_SetWindowLongA(h, idx, val);
    logf_("SetWindowLongA(%08X idx=%d val=0x%08X) -> 0x%08X", (DWORD)h, idx, (DWORD)val, (DWORD)r);
    return r;
}
static BOOL WINAPI h_SetWindowTextA(HWND h, LPCSTR s)
{
    BOOL r = o_SetWindowTextA(h, s);
    logf_("SetWindowTextA(%08X \"%s\") -> %d", (DWORD)h, s ? s : "", r);
    return r;
}

/* ---------------- IAT 补丁 ---------------- */
typedef struct { const char *name; void **slot; void *hook; } IAT_ENTRY;

static void patch_iat(void)
{
    HMODULE exe = GetModuleHandleA(NULL);
    if (!exe) return;
    BYTE *base = (BYTE *)exe;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return;
    IMAGE_DATA_DIRECTORY *dir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir->VirtualAddress) return;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir->VirtualAddress);

    IAT_ENTRY wants[] = {
        {"ShowWindow", NULL, (void *)h_ShowWindow},
        {"SetWindowPos", NULL, (void *)h_SetWindowPos},
        {"CreateWindowExA", NULL, (void *)h_CreateWindowExA},
        {"ChangeDisplaySettingsA", NULL, (void *)h_ChangeDisplaySettingsA},
        {"MoveWindow", NULL, (void *)h_MoveWindow},
        {"SetWindowLongA", NULL, (void *)h_SetWindowLongA},
        {"SetWindowTextA", NULL, (void *)h_SetWindowTextA},
    };
    const int nw = (int)(sizeof(wants) / sizeof(wants[0]));
    int patched = 0;

    for (; imp->Name; imp++) {
        const char *dll = (const char *)(base + imp->Name);
        int is_user32 = (lstrcmpiA(dll, "user32.dll") == 0);
        if (!is_user32) continue;
        IMAGE_THUNK_DATA *thunk = (IMAGE_THUNK_DATA *)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        IMAGE_THUNK_DATA *iat = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
        for (; thunk->u1.AddressOfData; thunk++, iat++) {
            if (thunk->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
            IMAGE_IMPORT_BY_NAME *ibn = (IMAGE_IMPORT_BY_NAME *)(base + thunk->u1.AddressOfData);
            for (int i = 0; i < nw; i++) {
                if (lstrcmpA((const char *)ibn->Name, wants[i].name) != 0) continue;
                DWORD old;
                void **slot = (void **)&iat->u1.Function;
                if (!VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &old)) break;
                switch (i) {
                    case 0: o_ShowWindow = (void *)*slot; break;
                    case 1: o_SetWindowPos = (void *)*slot; break;
                    case 2: o_CreateWindowExA = (void *)*slot; break;
                    case 3: o_ChangeDisplaySettingsA = (void *)*slot; break;
                    case 4: o_MoveWindow = (void *)*slot; break;
                    case 5: o_SetWindowLongA = (void *)*slot; break;
                    case 6: o_SetWindowTextA = (void *)*slot; break;
                }
                *slot = wants[i].hook;
                VirtualProtect(slot, sizeof(void *), old, &old);
                patched++;
                break;
            }
        }
    }
    logf_("IAT 补丁完成，替换 %d 个 user32 调用", patched);
}

/* ---------------- D3D9 钩子 ---------------- */
typedef HRESULT (WINAPI *PFN_CreateDevice)(IDirect3D9 *, UINT, D3DDEVTYPE, HWND, DWORD, D3DPRESENT_PARAMETERS *, IDirect3DDevice9 **);
static PFN_CreateDevice g_create;
static int g_patched_d3d;

static void dump_pp(const char *tag, D3DPRESENT_PARAMETERS *pp)
{
    if (!pp) { logf_("%s PP=NULL", tag); return; }
    logf_("%s Windowed=%d %ux%u fmt=%d depthEn=%d hz=%u swap=%d flags=0x%08X devWin=%08X",
          tag, pp->Windowed, pp->BackBufferWidth, pp->BackBufferHeight, pp->BackBufferFormat,
          pp->EnableAutoDepthStencil, pp->FullScreen_RefreshRateInHz, pp->SwapEffect,
          pp->Flags, (DWORD)pp->hDeviceWindow);
}

static HRESULT WINAPI hook_CreateDevice(IDirect3D9 *me, UINT Adapter, D3DDEVTYPE T, HWND Focus,
                                        DWORD Flags, D3DPRESENT_PARAMETERS *pp, IDirect3DDevice9 **ppDev)
{
    logf_(">>> CreateDevice adapter=%u type=%d hwnd=%08X flags=0x%08X", Adapter, T, (DWORD)Focus, Flags);
    dump_pp("    PP", pp);
    HRESULT hr = g_create(me, Adapter, T, Focus, Flags, pp, ppDev);
    logf_("<<< CreateDevice -> 0x%08X", (unsigned)hr);
    return hr;
}

static void patch_d3d(IDirect3D9 *p)
{
    if (g_patched_d3d || !p) return;
    void **vt = *(void ***)p;
    DWORD old;
    if (!VirtualProtect(&vt[16], sizeof(void *), PAGE_READWRITE, &old)) return;
    g_create = (PFN_CreateDevice)vt[16];
    vt[16] = (void *)hook_CreateDevice;
    VirtualProtect(&vt[16], sizeof(void *), old, &old);
    g_patched_d3d = 1;
    logf_("    IDirect3D9 vtable[16] 已替换 (%08X)", (DWORD)g_create);
}

__declspec(dllexport) IDirect3D9 * WINAPI Direct3DCreate9(UINT SDKVersion)
{
    if (!g_real) {
        char path[MAX_PATH];
        GetSystemDirectoryA(path, MAX_PATH);
        lstrcatA(path, "\\d3d9.dll");
        g_real = LoadLibraryA(path);
        if (g_real) pDirect3DCreate9 = (void *)GetProcAddress(g_real, "Direct3DCreate9");
    }
    if (!pDirect3DCreate9) return NULL;
    IDirect3D9 *p = pDirect3DCreate9(SDKVersion);
    logf_("=== Direct3DCreate9(%u) -> %08X", SDKVersion, (DWORD)p);
    patch_d3d(p);
    return p;
}

__declspec(dllexport) HRESULT WINAPI Direct3DCreate9Ex(UINT SDKVersion, IDirect3D9Ex **pp)
{
    logf_("=== Direct3DCreate9Ex(%u) 未支持", SDKVersion);
    return E_NOTIMPL;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID p)
{
    (void)p;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        logf_("--- d3d9 诊断代理加载 pid=%lu", GetCurrentProcessId());
        patch_iat();
    }
    return TRUE;
}
