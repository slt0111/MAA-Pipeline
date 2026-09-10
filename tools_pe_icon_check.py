# -*- coding: utf-8 -*-
"""检查 exe / ico 的图标资源，并报告每一帧的编码格式（PNG 帧 or DIB 帧）。

用法：
    python tools_pe_icon_check.py                       # 检查默认 exe
    python tools_pe_icon_check.py <path-to-exe-or-ico>
"""
import os
import struct
import sys

DEFAULT_EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MAA挂机助手.exe")

TYPES = {1: "RT_CURSOR", 2: "RT_BITMAP", 3: "RT_ICON", 4: "RT_MENU", 5: "RT_DIALOG",
         6: "RT_STRING", 12: "RT_GROUP_CURSOR", 14: "RT_GROUP_ICON", 16: "RT_VERSION",
         24: "RT_MANIFEST"}


def dump_ico(data, base, size, label):
    """解析一段 ICO 数据，报告每帧格式。"""
    if size < 6:
        print("   (%s 太小，跳过)" % label)
        return []
    reserved, itype, count = struct.unpack_from("<HHH", data, base)
    print("   %s: type=%d frames=%d" % (label, itype, count))
    out = []
    for i in range(count):
        e = base + 6 + i * 16
        w = data[e] or 256
        h = data[e + 1] or 256
        bpp = struct.unpack_from("<H", data, e + 6)[0]
        nbytes, off = struct.unpack_from("<II", data, e + 8)
        start = base + off
        is_png = data[start:start + 8] == b"\x89PNG\r\n\x1a\n"
        kind = "PNG" if is_png else "DIB"
        if not is_png:
            hs = struct.unpack_from("<I", data, start)[0]
            bpp = struct.unpack_from("<H", data, start + 14)[0]
        out.append((w, kind, bpp))
        print("      %3dx%-3d %-4s bpp=%-3d %7d bytes" % (w, h, kind, bpp, nbytes))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXE
    data = open(path, "rb").read()
    print("file: %s  (%d bytes)" % (path, len(data)))

    if data[:4] == b"\x00\x00\x01\x00" or path.lower().endswith(".ico"):
        print("\n== ICO 文件 ==")
        frames = dump_ico(data, 0, len(data), "app.ico")
        dib = [f for f in frames if f[1] == "DIB"]
        png = [f for f in frames if f[1] == "PNG"]
        print("\n小结：DIB 帧 %d 个 / PNG 帧 %d 个" % (len(dib), len(png)))
        small_bad = [f for f in frames if f[0] < 256 and f[1] == "PNG"]
        if small_bad:
            print(">>> 警告：以下小尺寸用了 PNG 帧，Windows shell 可能渲染不出来：%s"
                  % [f[0] for f in small_bad])
        else:
            print(">>> OK：小尺寸全部为 DIB 帧，256 为 PNG 帧，兼容性最佳")
        return 0

    if data[:2] != b"MZ":
        print("不是 PE 也不是 ICO")
        return 1

    e = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[e:e + 4] == b"PE\x00\x00"
    coff = e + 4
    _, nsec, _, _, _, optsize, _ = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20b else 96)
    res_rva, res_size = struct.unpack_from("<II", data, dd + 16)

    secs = []
    secoff = opt + optsize
    for i in range(nsec):
        name, vsize, vaddr, rsize, raddr = struct.unpack_from("<8sIIII", data, secoff + i * 40)[:5]
        secs.append((name.rstrip(b"\x00").decode(errors="replace"), vaddr, vsize, raddr, rsize))

    def rva2off(rva):
        for n, va, vs, ra, rs in secs:
            if va <= rva < va + max(vs, rs):
                return ra + (rva - va)
        return None

    base = rva2off(res_rva)
    if base is None:
        print("没有资源节")
        return 1

    def walk(off, label=""):
        out = []
        if off + 16 > len(data):
            return out
        chars, ts, maj, minr, nnamed, nid = struct.unpack_from("<IIHHHH", data, off)
        for i in range(nnamed + nid):
            e2 = off + 16 + i * 8
            name, offset = struct.unpack_from("<II", data, e2)
            nm = "named" if (name & 0x80000000) else (name & 0xFFFF)
            full = ("%s/%s" % (label, nm)).strip("/")
            if offset & 0x80000000:
                out += walk(base + (offset & 0x7FFFFFFF), full)
            else:
                # DataEntry.OffsetToData 是 RVA，要换成文件偏移才能读到真实字节
                doff_rva, dsize = struct.unpack_from("<II", data, base + offset)[:2]
                out.append((full, rva2off(doff_rva), dsize))
        return out

    entries = walk(base)
    if not entries:
        print("资源节为空")
        return 1
    types = {}
    for name, doff, dsize in entries:
        t = name.split("/")[0]
        types.setdefault(t, []).append((name, doff, dsize))

    print("\n== PE 资源 ==")
    for t in sorted(types, key=lambda x: int(x) if x.isdigit() else 999):
        tn = TYPES.get(int(t), "?") if t.isdigit() else "?"
        print("  type %-4s %-16s x%d" % (t, tn, len(types[t])))

    print("\n== 图标帧 ==")
    if "3" not in types:
        print("  !! 没有 RT_ICON —— exe 未嵌入图标，资源管理器会显示空白图标")
        return 1
    total_dib = total_png = 0
    for name, doff, dsize in types["3"]:
        blob = data[doff:doff + dsize]
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            total_png += 1
        else:
            total_dib += 1
    print("  DIB 帧 %d 个 / PNG 帧 %d 个（共 %d 个）"
          % (total_dib, total_png, total_dib + total_png))
    return 0


if __name__ == "__main__":
    sys.exit(main())
