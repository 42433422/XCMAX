#!/usr/bin/env python3
"""
生成 desktop/resources 下 NSIS 安装包位图与应用图标（icon.png / icon.ico）。
在 macOS 上若存在 iconutil/sips，同时生成 icon.icns。

品牌图源：将 ``desktop/branding/app-icon-source.png`` 放入仓库后，打包前脚本会
据此生成 exe/安装包/托盘用图标；若缺失则回退为内置渐变占位图。

依赖：Pillow（与仓库 requirements 一致）。从仓库根目录执行。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "desktop" / "resources"
BRAND_SOURCE = ROOT / "desktop" / "branding" / "app-icon-source.png"

# 与旧版 create-installer-assets.ps1 视觉接近的配色（仅作背景；前景为品牌图）
C_TOP = (24, 54, 96)
C_BOTTOM = (47, 128, 237)
WHITE = (255, 255, 255)
MUTED = (240, 247, 255)


def _try_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        "msyh.ttc",
        "Microsoft YaHei",
        "Microsoft YaHei UI",
        "Segoe UI",
        "Arial Unicode MS",
        "Arial",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_bitmap(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(C_TOP[0] + (C_BOTTOM[0] - C_TOP[0]) * t)
        g = int(C_TOP[1] + (C_BOTTOM[1] - C_TOP[1]) * t)
        b = int(C_TOP[2] + (C_BOTTOM[2] - C_TOP[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    draw.ellipse((-40, -35, 90, 95), fill=(230, 240, 255))
    draw.ellipse((width - 80, height - 90, width + 50, height + 40), fill=(230, 240, 255))
    return img


def _white_to_transparent(im: Image.Image, threshold: int = 250) -> Image.Image:
    """将近白背景转为透明，便于 Windows 任务栏/桌面图标边缘自然。"""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                px[x, y] = (r, g, b, 0)
    return rgba


def _load_brand_rgba() -> Image.Image | None:
    if not BRAND_SOURCE.is_file():
        return None
    try:
        im = Image.open(BRAND_SOURCE).convert("RGBA")
    except OSError:
        return None
    return _white_to_transparent(im, threshold=248)


def _square_canvas_rgba(im: Image.Image, size: int) -> Image.Image:
    """等比缩放后居中贴到 size×size 透明方画布（用于 .ico / 应用图标）。"""
    im = im.convert("RGBA")
    w, h = im.size
    if w <= 0 or h <= 0:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))
    scale = min(size / w, size / h)
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2), resized)
    return canvas


def _draw_app_icon_rgba(size: int) -> Image.Image:
    """无品牌图源时的占位图标。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base = _gradient_bitmap(size, size).convert("RGBA")
    img.paste(base, (0, 0))
    draw = ImageDraw.Draw(img)
    f = _try_font(max(size // 6, 14))
    text = "XCAGI"
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, (size - th) // 2 - size // 28), text, fill=WHITE, font=f)
    return img


def _app_icon_master_512() -> Image.Image:
    brand = _load_brand_rgba()
    if brand is not None:
        return _square_canvas_rgba(brand, 512)
    return _draw_app_icon_rgba(512)


def _paste_logo_on_rgb(bg: Image.Image, logo_rgba: Image.Image, box: tuple[int, int, int, int]) -> None:
    """将 RGBA logo 等比放入 box (l,t,r,b) 并 composite 回 RGB 背景。"""
    l, t, r, b = box
    bw, bh = r - l, b - t
    if bw < 2 or bh < 2:
        return
    lw, lh = logo_rgba.size
    scale = min(bw / lw, bh / lh)
    nw = max(1, int(lw * scale))
    nh = max(1, int(lh * scale))
    resized = logo_rgba.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = l + (bw - nw) // 2
    oy = t + (bh - nh) // 2
    bg_rgba = bg.convert("RGBA")
    bg_rgba.paste(resized, (ox, oy), resized)
    rgb_out = bg_rgba.convert("RGB")
    bg.paste(rgb_out, (0, 0))


def write_installer_sidebar() -> None:
    w, h = 164, 314
    img = _gradient_bitmap(w, h)
    draw = ImageDraw.Draw(img)
    title_font = _try_font(18)
    sub_font = _try_font(8)
    small_font = _try_font(7)
    brand = _load_brand_rgba()
    if brand is not None:
        _paste_logo_on_rgb(img, brand, (12, 16, 152, 120))
        title_y, sub_y = 130, 164
    else:
        title_y, sub_y = 38, 72
    draw.text((16, title_y), "XCAGI", fill=WHITE, font=title_font)
    draw.text((17, sub_y), "Enterprise AI Employee", fill=MUTED, font=sub_font)
    draw.text((17, 244), "Desktop + Web Delivery", fill=MUTED, font=small_font)
    draw.text((17, 266), "xiu-ci" if brand is not None else "v7.0", fill=MUTED, font=small_font)
    img.save(OUT / "installer-sidebar.bmp", format="BMP")


def write_installer_header() -> None:
    w, h = 150, 57
    img = _gradient_bitmap(w, h)
    draw = ImageDraw.Draw(img)
    title_font = _try_font(16)
    small_font = _try_font(7)
    brand = _load_brand_rgba()
    if brand is not None:
        _paste_logo_on_rgb(img, brand, (6, 4, 56, 53))
        tx, ty, sx, sy = 62, 10, 64, 36
    else:
        tx, ty, sx, sy = 12, 8, 14, 38
    draw.text((tx, ty), "XCAGI", fill=WHITE, font=title_font)
    draw.text((sx, sy), "Desktop Installer", fill=MUTED, font=small_font)
    img.save(OUT / "installer-header.bmp", format="BMP")


def write_icon_png_and_ico() -> None:
    img512 = _app_icon_master_512()
    OUT.mkdir(parents=True, exist_ok=True)
    img512.save(OUT / "icon.png", format="PNG")
    # Windows 优先读取 ICO 内较大尺寸；首张用 256，其余 append（避免仅写入 16×16）
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    imgs = [_square_canvas_rgba(img512, s[0]) for s in sizes]
    imgs[0].save(OUT / "icon.ico", format="ICO", append_images=imgs[1:])


def write_icns_darwin() -> None:
    if sys.platform != "darwin":
        return
    if not shutil.which("iconutil") or not shutil.which("sips"):
        print("[generate-desktop-resources] 跳过 icon.icns（未找到 iconutil/sips）", file=sys.stderr)
        return
    png_master = OUT / "icon.png"
    if not png_master.exists():
        return
    iconset = OUT / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    def sip(out_name: str, px: int) -> None:
        dest = iconset / out_name
        subprocess.run(
            ["sips", "-z", str(px), str(px), str(png_master), "--out", str(dest)],
            check=True,
            capture_output=True,
        )

    # macOS iconset 常用命名（满足 iconutil）
    sip("icon_16x16.png", 16)
    sip("icon_16x16@2x.png", 32)
    sip("icon_32x32.png", 32)
    sip("icon_32x32@2x.png", 64)
    sip("icon_128x128.png", 128)
    sip("icon_128x128@2x.png", 256)
    sip("icon_256x256.png", 256)
    sip("icon_256x256@2x.png", 512)
    sip("icon_512x512.png", 512)
    sip("icon_512x512@2x.png", 1024)

    icns_out = OUT / "icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns_out)], check=True)
    shutil.rmtree(iconset, ignore_errors=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if BRAND_SOURCE.is_file():
        print(f"[generate-desktop-resources] 使用品牌图源: {BRAND_SOURCE}")
    else:
        print(f"[generate-desktop-resources] 未找到 {BRAND_SOURCE}，使用占位图标")
    write_installer_sidebar()
    write_installer_header()
    write_icon_png_and_ico()
    write_icns_darwin()
    print(f"Desktop resources written to: {OUT}")


if __name__ == "__main__":
    main()
