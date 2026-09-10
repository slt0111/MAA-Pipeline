# -*- coding: utf-8 -*-
"""生成应用图标 app.ico（多尺寸），供 PyInstaller 打包与窗口图标使用。

设计：深蓝→青绿渐变圆角方块 + 白色闪电，呼应"一键自动挂机"。
小尺寸单独绘制（笔画更粗），避免缩放后糊成一团。

重要：ICO 里的每一帧编码方式有讲究——
    · 16/24/32/48/64/128 用 BMP(DIB) 帧，这是 Windows 资源管理器/任务栏
      兼容性最好的格式；
    · 256 用 PNG 帧（BMP 会让 ico 体积暴涨）。
早前所有尺寸都用 PNG 帧，结果 shell 渲染不出来，exe 显示为空白图标。

用法：
    python make_icon.py           生成 app.ico
    python make_icon.py --preview 同时导出 preview.png 便于肉眼确认
"""

from __future__ import annotations

import os
import struct
import sys

from PIL import Image, ImageDraw

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(APP_DIR, "app.ico")
PREVIEW_PATH = os.path.join(APP_DIR, "preview.png")

SIZES = [16, 24, 32, 48, 64, 128, 256]
SUPERSAMPLE = 4

# 配色取自界面主题：蓝 → 青绿
COLOR_TOP = (0x18, 0x5F, 0xA5)
COLOR_BOTTOM = (0x0F, 0x6E, 0x56)

# 闪电多边形（相对坐标，0~1）。顶点按顺时针排列。
BOLT = [
    (0.615, 0.055),
    (0.245, 0.545),
    (0.455, 0.545),
    (0.385, 0.945),
    (0.755, 0.445),
    (0.545, 0.445),
]


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _bolt_points(size: float, compact: bool):
    """把相对坐标换算成像素坐标。compact=True 时收紧一些，小图标更饱满。"""
    pts = []
    for rx, ry in BOLT:
        x = rx if not compact else 0.5 + (rx - 0.5) * 1.04
        y = ry
        pts.append((x * size, y * size))
    return pts


def draw_icon(px: int) -> Image.Image:
    """绘制单张图标，返回 px×px 的 RGBA 图。"""
    s = px * SUPERSAMPLE
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 圆角半径：小图标用更小的相对圆角，避免边缘只剩圆弧
    radius = int(s * (0.30 if px <= 24 else 0.235))

    # 渐变底：逐行画线，比逐像素快得多
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        gd.line([(0, y), (s, y)], fill=_lerp(COLOR_TOP, COLOR_BOTTOM, y / max(1, s - 1)) + (255,))

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)
    base.paste(grad, (0, 0), mask)

    # 顶部高光，让图标有点体积感
    gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).rounded_rectangle(
        [0, 0, s - 1, int(s * 0.46)], radius=radius, fill=(255, 255, 255, 30)
    )
    base = Image.alpha_composite(base, Image.composite(
        gloss, Image.new("RGBA", (s, s), (0, 0, 0, 0)), mask
    ))

    # 白色闪电
    bolt = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(bolt).polygon(
        _bolt_points(s, compact=px <= 32), fill=(255, 255, 255, 255)
    )
    base = Image.alpha_composite(base, bolt)

    return base.resize((px, px), Image.LANCZOS)


def _png_frame(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _bmp_frame(img: Image.Image) -> bytes:
    """把 RGBA 图编码成 ICO 内嵌的 BMP(DIB) 帧：BITMAPINFOHEADER + BGRA + AND 掩码。

    Windows shell 对 DIB 帧的支持是最好的一档，小尺寸必须走这条路。
    """
    img = img.convert("RGBA")
    size = img.width
    px = img.load()
    rows = []
    for y in range(size - 1, -1, -1):        # DIB 是自下而上
        row = bytearray()
        for x in range(size):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))       # BGRA
        rows.append(bytes(row))
    xor = b"".join(rows)
    mask_stride = ((size + 31) // 32) * 4    # AND 掩码每行按 4 字节对齐
    and_mask = b"\x00" * (mask_stride * size)  # 全 0：透明度交给 alpha 通道
    header = struct.pack(
        "<IiiHHIIiiII",
        40,             # biSize
        size,           # biWidth
        size * 2,       # biHeight（XOR + AND 两张图）
        1,              # biPlanes
        32,             # biBitCount
        0,              # biCompression = BI_RGB
        len(xor),       # biSizeImage
        0, 0, 0, 0,     # 分辨率与调色板
    )
    return header + xor + and_mask


def build_ico(pngs, out_path: str):
    """把各尺寸图组装成 ICO：≥256 用 PNG 帧，其余用 BMP 帧（兼容性优先）。"""
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)          # reserved, type=icon, count
    entries = b""
    payload = b""
    offset = 6 + 16 * count
    for size, blob in pngs:
        dim = 0 if size >= 256 else size               # 256 记为 0
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        payload += blob
    with open(out_path, "wb") as fh:
        fh.write(header + entries + payload)


def main():
    pngs = []
    for size in SIZES:
        img = draw_icon(size)
        # 256 走 PNG，小尺寸走 DIB —— 见文件头部说明
        blob = _png_frame(img) if size >= 256 else _bmp_frame(img)
        pngs.append((size, blob))
        print("  绘制 %3d×%-3d  %-3s  %6d 字节"
              % (size, size, "PNG" if size >= 256 else "DIB", len(blob)))

    build_ico(pngs, ICO_PATH)
    print("\n图标已生成：%s（%d 个尺寸，%.1f KB）"
          % (ICO_PATH, len(pngs), os.path.getsize(ICO_PATH) / 1024))

    if "--preview" in sys.argv:
        draw_icon(256).save(PREVIEW_PATH)
        print("预览图：%s" % PREVIEW_PATH)


if __name__ == "__main__":
    main()
