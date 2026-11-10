#include <windows.h>

/* 通过“改写返回地址”实现无显式调用的钩子：
   my_ggo 保存 6 个参数与返回地址，把返回地址换成 post_handler，然后尾跳原函数。
   原函数 ret 后直接进入 post_handler，此时 ESP 已恢复到调用者期望的位置。 */

typedef DWORD (WINAPI *GGO_t)(HDC, UINT, UINT, LPGLYPHMETRICS, DWORD, LPVOID);

extern const unsigned char cn_map_data[];
extern const unsigned int cn_map_count;

static GGO_t g_fn;
static unsigned char *g_view;

/* 用固定名字，方便汇编引用（MinGW 会在前面加下划线） */
struct ctx {
    DWORD ret;
    DWORD a1, a2, a3, a4, a5, a6;
} g_ctx;

void __cdecl post_work(DWORD r);

__attribute__((naked)) void post_handler(void)
{
    __asm__ __volatile__(
        "pushal\n\t"
        "pushl 28(%esp)\n\t"
        "call _post_work\n\t"
        "addl $4, %esp\n\t"
        "popal\n\t"
        "jmp *_g_ctx\n\t"
    );
}

__attribute__((naked)) static void my_ggo(void)
{
    __asm__ __volatile__(
        "movl 0(%esp), %eax\n\t"
        "movl %eax, _g_ctx+0\n\t"
        "movl 4(%esp), %eax\n\t"
        "movl %eax, _g_ctx+4\n\t"
        "movl 8(%esp), %eax\n\t"
        "movl %eax, _g_ctx+8\n\t"
        "movl 12(%esp), %eax\n\t"
        "movl %eax, _g_ctx+12\n\t"
        "movl 16(%esp), %eax\n\t"
        "movl %eax, _g_ctx+16\n\t"
        "movl 20(%esp), %eax\n\t"
        "movl %eax, _g_ctx+20\n\t"
        "movl 24(%esp), %eax\n\t"
        "movl %eax, _g_ctx+24\n\t"
        "movl $_post_handler, %eax\n\t"
        "movl %eax, 0(%esp)\n\t"
        "jmp *_g_fn\n\t"
    );
}

/* 原函数返回后在这里执行；EAX 是返回值（已由 pushal 保存） */
void __cdecl post_work(DWORD r)
{
    DWORD uChar = g_ctx.a2;
    DWORD fuFormat = g_ctx.a3;
    LPGLYPHMETRICS lpgm = (LPGLYPHMETRICS)g_ctx.a4;
    DWORD cjBuffer = g_ctx.a5;
    LPVOID pvBuffer = (LPVOID)g_ctx.a6;
    if (g_view) {
        unsigned int n = *(unsigned int *)g_view;
        if (n < 20000) {
            unsigned char *p = g_view + 4 + n * 6;
            *(unsigned short *)p = (unsigned short)uChar;
            *(unsigned int *)(p + 2) = r;
            *(unsigned int *)g_view = n + 1;
        }
    }

    if (pvBuffer && cjBuffer && r != (DWORD)-1 && (fuFormat & 0x0F) == 6) {
        const unsigned char *buf = cn_map_data;
        unsigned int i, off = 4;
        for (i = 0; i < cn_map_count; i++) {
            unsigned int c = *(const unsigned short *)(buf + off);
            unsigned int sw = buf[off + 2];
            unsigned int sh = buf[off + 3];
            if (c == uChar) {
                unsigned int w = lpgm->gmBlackBoxX;
                unsigned int hh = lpgm->gmBlackBoxY;
                unsigned int stride = (w + 3) & ~3u;
                if (w && hh && sw && sh && stride * hh <= cjBuffer) {
                    const unsigned char *px = buf + off + 4;
                    unsigned char *dst = (unsigned char *)pvBuffer;
                    unsigned int x, y;
                    unsigned int dw, dh, ox, oy;
                    /* 先清空目标区域 */
                    for (y = 0; y < hh; y++) {
                        unsigned char *row = dst + y * stride;
                        for (x = 0; x < w; x++) row[x] = 0;
                    }
                    /* 等比缩放，居中放置 */
                    if (sw * hh <= sh * w) {          /* 以高度为准 */
                        dh = hh;
                        dw = (sw * hh) / sh;
                    } else {                           /* 以宽度为准 */
                        dw = w;
                        dh = (sh * w) / sw;
                    }
                    if (!dw) dw = 1;
                    if (!dh) dh = 1;
                    ox = (w - dw) / 2;
                    oy = (hh - dh) / 2;
                    if (dw == sw && dh == sh) {
                        /* 1:1，直接拷贝（字库已按原生尺寸生成） */
                        for (y = 0; y < dh; y++) {
                            unsigned char *row = dst + (oy + y) * stride + ox;
                            const unsigned char *sr = px + y * sw;
                            for (x = 0; x < dw; x++) row[x] = sr[x];
                        }
                    } else {
                        /* 面积平均下采样（替代最近邻，避免笔画断裂/发糊） */
                        for (y = 0; y < dh; y++) {
                            unsigned int y0 = y * sh / dh, y1 = (y + 1) * sh / dh;
                            unsigned char *row = dst + (oy + y) * stride + ox;
                            if (y1 <= y0) y1 = y0 + 1;
                            if (y1 > sh) y1 = sh;
                            for (x = 0; x < dw; x++) {
                                unsigned int x0 = x * sw / dw, x1 = (x + 1) * sw / dw;
                                unsigned int s = 0, n = 0, yy, xx;
                                if (x1 <= x0) x1 = x0 + 1;
                                if (x1 > sw) x1 = sw;
                                for (yy = y0; yy < y1; yy++) {
                                    const unsigned char *sr = px + yy * sw;
                                    for (xx = x0; xx < x1; xx++) { s += sr[xx]; n++; }
                                }
                                row[x] = n ? (unsigned char)(s / n) : 0;
                            }
                        }
                    }
                }
                break;
            }
            off += 4 + sw * sh;
        }
    }
}

static int eqi(const char *a, const char *b)
{
    for (;;) {
        char x = *a, y = *b;
        if (x >= 'A' && x <= 'Z') x += 32;
        if (y >= 'A' && y <= 'Z') y += 32;
        if (x != y) return 0;
        if (!x) return 1;
        a++; b++;
    }
}

static unsigned char *rva2ptr(unsigned char *base, DWORD rva)
{
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    IMAGE_SECTION_HEADER *sec = IMAGE_FIRST_SECTION(nt);
    int i;
    for (i = 0; i < nt->FileHeader.NumberOfSections; i++) {
        DWORD va = sec[i].VirtualAddress;
        if (rva >= va && rva < va + sec[i].Misc.VirtualSize) return base + rva;
    }
    return base + rva;
}

static void patch_iat(const char *dllname, const char *funcname, void *newfn)
{
    unsigned char *base = (unsigned char *)GetModuleHandleA(NULL);
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    IMAGE_IMPORT_DESCRIPTOR *imp =
        (IMAGE_IMPORT_DESCRIPTOR *)rva2ptr(base, nt->OptionalHeader.DataDirectory[1].VirtualAddress);
    int i, k;
    for (i = 0; imp[i].Name; i++) {
        const char *mod = (const char *)rva2ptr(base, imp[i].Name);
        IMAGE_THUNK_DATA *thunk, *orig;
        if (!eqi(mod, dllname)) continue;
        thunk = (IMAGE_THUNK_DATA *)rva2ptr(base, imp[i].FirstThunk);
        orig  = (IMAGE_THUNK_DATA *)rva2ptr(base, imp[i].OriginalFirstThunk ? imp[i].OriginalFirstThunk : imp[i].FirstThunk);
        for (k = 0; orig[k].u1.AddressOfData; k++) {
            if (!(orig[k].u1.Ordinal & IMAGE_ORDINAL_FLAG)) {
                IMAGE_IMPORT_BY_NAME *nm = (IMAGE_IMPORT_BY_NAME *)rva2ptr(base, (DWORD)orig[k].u1.AddressOfData);
                if (eqi((const char *)nm->Name, funcname)) {
                    DWORD old;
                    if (!g_fn) g_fn = (GGO_t)thunk[k].u1.Function;
                    VirtualProtect(&thunk[k].u1.Function, 4, PAGE_READWRITE, &old);
                    thunk[k].u1.Function = (DWORD)newfn;
                    VirtualProtect(&thunk[k].u1.Function, 4, old, &old);
                }
            }
        }
    }
}

BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID reserved)
{
    (void)hinst; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        HANDLE h = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
                                      0, 65536, "SilveryTrace");
        if (h) g_view = (unsigned char *)MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, 65536);
        patch_iat("gdi32.dll", "GetGlyphOutlineA", (void *)my_ggo);
    }
    return TRUE;
}
