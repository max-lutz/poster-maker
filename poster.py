"""Retro poster generator — starter version (classic overlap layout)."""
import sys
import tomllib
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

PAPER_MM = {"A4": (210, 297), "A3": (297, 420)}
DESIGN_W = 794  # all layout numbers below are designed on a 794 px wide page


def mm_to_px(mm: float, dpi: int) -> int:
    return round(mm / 25.4 * dpi)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------- effects ----------

def vintage(photo: Image.Image, saturation=0.85, contrast=0.92, warmth=0.05, fade=0.06):
    """Faded, slightly warm film look."""
    photo = ImageEnhance.Color(photo).enhance(saturation)
    photo = ImageEnhance.Contrast(photo).enhance(contrast)
    a = np.asarray(photo).astype(np.float32)
    a[..., 0] *= 1 + warmth          # more red
    a[..., 2] *= 1 - warmth          # less blue
    a = a * (1 - fade) + 255 * fade  # lift the blacks
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def add_grain(img: Image.Image, strength: float = 14, seed: int = 0) -> Image.Image:
    """Monochrome film grain over the whole poster."""
    rng = np.random.default_rng(seed)
    a = np.asarray(img).astype(np.int16)
    noise = rng.normal(0, strength, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a + noise, 0, 255).astype(np.uint8))


def make_qr(url: str, size: int, ink) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=ink, back_color="white").convert("RGB")
    return img.resize((size, size), Image.NEAREST)  # NEAREST keeps modules sharp


def fit_font(draw, text, font_path, target_w):
    """Largest font size whose text width is <= target_w."""
    lo, hi = 10, 2000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = ImageFont.truetype(font_path, mid)
        if draw.textlength(text, font=f) <= target_w:
            lo = mid
        else:
            hi = mid - 1
    return ImageFont.truetype(font_path, lo)


def crop_mark(draw, cx, cy, arm, width, color):
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=color, width=width)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=color, width=width)


# ---------- layout ----------

def render_classic(cfg: dict, base: Path) -> Image.Image:
    p, fonts = cfg["poster"], cfg["fonts"]
    w_mm, h_mm = PAPER_MM[p["size"]]
    W, H = mm_to_px(w_mm, p["dpi"]), mm_to_px(h_mm, p["dpi"])
    u = W / DESIGN_W                     # scale factor: design px -> print px
    s = lambda v: round(v * u)
    ink, accent = hex_rgb(p["ink"]), hex_rgb(p["accent"])

    poster = Image.new("RGB", (W, H), hex_rgb(p["paper"]))
    d = ImageDraw.Draw(poster)

    # crop marks
    for cx in (s(52), W - s(52)):
        crop_mark(d, cx, s(52), s(24), max(2, s(1.5)), ink)

    # info row
    label_f = ImageFont.truetype(str(base / fonts["label"]), s(16))
    mono_f = ImageFont.truetype(str(base / fonts["mono"]), s(13))
    info = p["info"]
    col_w = (W - s(80)) / len(info)
    for i, item in enumerate(info):
        x = s(40) + i * col_w
        d.text((x, s(440)), f'{item["label"]} -', font=label_f, fill=ink)
        d.text((x, s(464)), item["value"], font=mono_f, fill=ink)

    # photo block
    box = (s(24), s(610), W - s(24), H - s(40))
    photo = ImageOps.exif_transpose(Image.open(base / p["photo"])).convert("RGB")
    photo = ImageOps.fit(photo, (box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
    poster.paste(vintage(photo), box[:2])

    # title, overlapping the top of the photo
    title_f = fit_font(d, p["title"], str(base / fonts["title"]), W * 0.80)
    top_offset = title_f.getbbox(p["title"])[1]       # remove the font's empty top space
    d.text((s(26), s(492) - top_offset), p["title"], font=title_f, fill=accent)

    # tagline + QR code
    qr_size = s(104)
    qr = make_qr(p["url"], qr_size, ink)
    pad = s(10)
    qx = (W - qr_size) // 2
    qy = H - s(64) - qr_size - pad
    d.rectangle([qx - pad, qy - pad, qx + qr_size + pad, qy + qr_size + pad], fill="white")
    poster.paste(qr, (qx, qy))

    tag_f = ImageFont.truetype(str(base / fonts["label"]), s(17))
    tw = d.textlength(p["tagline"], font=tag_f)
    ty = qy - pad - s(34)
    d.rectangle([(W - tw) / 2 - s(10), ty - s(4), (W + tw) / 2 + s(10), ty + s(26)],
                fill=hex_rgb(p["paper"]))
    d.text(((W - tw) / 2, ty), p["tagline"], font=tag_f, fill=ink)

    return add_grain(poster, p.get("grain", 14))


LAYOUTS = {"classic": render_classic}


def main(config_path: str):
    config_path = Path(config_path)
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent.parent  # project root (config/ is one level down)
    p = cfg["poster"]
    img = LAYOUTS[p["layout"]](cfg, base)
    out = base / "output" / f'{p["title"].lower()}_{p["layout"]}_{p["size"]}.png'
    out.parent.mkdir(exist_ok=True)
    img.save(out, dpi=(p["dpi"], p["dpi"]))
    print(f"Saved {out}  ({img.width}x{img.height} px)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config/poster.toml")
