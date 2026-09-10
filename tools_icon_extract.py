# -*- coding: utf-8 -*-
"""把 exe（或 ico）里的图标帧解码成 PNG，用来肉眼确认图标到底长什么样。

用法：
    python tools_icon_extract.py <exe-or-ico> <输出目录>
"""
import os
import struct
import sys

from PIL import Image


def dib_to_image(blob: bytes) -> Image.Image:
    hs = struct.unpack_from("<I", blob, 0)[0]
    w = struct.unpack_from("<i", blob, 4)[0]
    h2 = struct.unpack_from("<i", blob, 8)[0]
    bpp = struct.unpack_from("<H", blob, 14)[0]
    h = h2 // 2
    if bpp != 32:
        raise ValueError("only 32bpp supported, got %d" % bpp)
    px = blob[hs:hs + w * h * 4]
    img = Image.frombytes("RGBA", (w, h), px, "raw", "BGRA")
    return img.transpose(Image.FLIP_TOP_BOTTOM)


def save_frame(blob: bytes, out_dir: str, tag: str, size_hint: int):
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        import io

        img = Image.open(io.BytesIO(blob))
    else:
        img = dib_to_image(blob)
    name = "%s_%dx%d.png" % (tag, img.width, img.height)
    path = os.path.join(out_dir, name)
    img.save(path)
    # 顺带报一下中心像素与角像素，判断是不是空白图
    cx, cy = img.width // 2, img.height // 2
    print("   %-28s size=%dx%d  中心像素=%s  左上像素=%s"
          % (name, img.width, img.height, img.getpixel((cx, cy)), img.getpixel((0, 0))))
    return path


def from_ico(data: bytes, out_dir: str):
    _, _, count = struct.unpack_from("<HHH", data, 0)
    print("ICO 帧数：%d" % count)
    for i in range(count):
        e = 6 + i * 16
        w = data[e] or 256
        nbytes, off = struct.unpack_from("<II", data, e + 8)
        save_frame(data[off:off + nbytes], out_dir, "ico", w)


def from_exe(data: bytes, out_dir: str):
    e = struct.unpack_from("<I", data, 0x3C)[0]
    coff = e + 4
    _, nsec, _, _, _, optsize, _ = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20b else 96)
    res_rva, _ = struct.unpack_from("<II", data, dd + 16)
    secs = []
    secoff = opt + optsize
    for i in range(nsec):
        name, vsize, vaddr, rsize, raddr = struct.unpack_from("<8sIIII", data, secoff + i * 40)[:5]
        secs.append((vaddr, vsize, raddr, rsize))

    def rva2off(rva):
        for va, vs, ra, rs in secs:
            if va <= rva < va + max(vs, rs):
                return ra + (rva - va)
        return None

    base = rva2off(res_rva)

    def walk(off, label=""):
        out = []
        if off + 16 > len(data):
            return out
        _, _, _, _, nnamed, nid = struct.unpack_from("<IIHHHH", data, off)
        for i in range(nnamed + nid):
            e2 = off + 16 + i * 8
            name, offset = struct.unpack_from("<II", data, e2)
            nm = "named" if (name & 0x80000000) else (name & 0xFFFF)
            full = ("%s/%s" % (label, nm)).strip("/")
            if offset & 0x80000000:
                out += walk(base + (offset & 0x7FFFFFFF), full)
            else:
                # DataEntry.OffsetToData 存的是 RVA，必须再换算成文件偏移
                doff_rva, dsize = struct.unpack_from("<II", data, base + offset)[:2]
                out.append((full, rva2off(doff_rva), dsize))
        return out

    icons = [x for x in walk(base) if x[0].split("/")[0] == "3"]
    print("RT_ICON 帧数：%d" % len(icons))
    for name, doff, dsize in icons:
        save_frame(data[doff:doff + dsize], out_dir, "exe_icon_" + name.replace("/", "_"), 0)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "MAA挂机助手.exe")
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(src), "_icon_frames")
    os.makedirs(out_dir, exist_ok=True)
    data = open(src, "rb").read()
    if data[:4] == b"\x00\x00\x01\x00":
        from_ico(data, out_dir)
    else:
        from_exe(data, out_dir)
    print("\n输出目录：%s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
