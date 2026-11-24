"""產生 App 圖示（只需要在開發時執行一次；需要 Pillow：pip install pillow）。

python tools/make_icons.py
"""
import os

from PIL import Image, ImageDraw

TEAL = (47, 125, 109, 255)
ORANGE = (217, 130, 43, 255)
WHITE = (255, 255, 255, 255)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "icons")
S = 1024  # 先畫大圖再縮小，邊緣比較平滑


def draw_mark(img, scale=1.0):
    d = ImageDraw.Draw(img)
    c = S / 2

    def p(x, y):  # 以畫布中心縮放
        return c + (x - c) * scale, c + (y - c) * scale

    # 壺鈴把手（白色環）與身體
    x0, y0 = p(282, 200)
    x1, y1 = p(742, 600)
    d.ellipse([x0, y0, x1, y1], outline=WHITE, width=int(86 * scale))
    x0, y0 = p(222, 380)
    x1, y1 = p(802, 880)
    d.ellipse([x0, y0, x1, y1], fill=WHITE)
    # 身體上的進步折線
    pts = [p(352, 712), p(452, 640), p(540, 676), p(660, 560)]
    d.line(pts, fill=TEAL, width=int(40 * scale), joint="curve")
    for pt in pts[:-1]:
        r = 24 * scale
        d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=TEAL)
    r = 40 * scale
    ex, ey = pts[-1]
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=ORANGE)


def full_bleed(scale):
    img = Image.new("RGBA", (S, S), TEAL)
    draw_mark(img, scale)
    return img


def rounded():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=TEAL)
    draw_mark(img, 0.92)
    return img


def save(img, size, name, rgb=False):
    out = img.resize((size, size), Image.LANCZOS)
    if rgb:
        out = out.convert("RGB")
    out.save(os.path.join(OUT, name))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    save(full_bleed(0.92), 180, "apple-touch-icon.png", rgb=True)  # iOS 會自動切圓角
    r = rounded()
    save(r, 192, "icon-192.png")
    save(r, 512, "icon-512.png")
    save(full_bleed(0.75), 512, "icon-maskable-512.png", rgb=True)  # 內容留在安全區內
    print("icons written to", OUT)
