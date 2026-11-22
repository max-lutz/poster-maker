"""Retro poster generator, "gallery" layout.

A full-width photo with a giant title whose letters are filled by the same
photo continuing upward. Info row and a Spotify code (or QR code) sit below.
The page orientation follows the photo.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

PAPER_MM = {"A4": (210, 297), "A3": (297, 420)}
DESIGN_W = 794  # layout numbers are designed on a 794 px wide page (A4 at 96 DPI)
EFFECTS = dict(saturation=0.85, contrast=0.92, warmth=0.05, fade=0.06,
               grain=7, texture=1.0, creases=3)


# ---------- units, sizes, orientation ----------

def mm_to_px(mm: float, dpi: int) -> int:
    return round(mm / 25.4 * dpi)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def paper_mm(size: str) -> tuple[float, float]:
    """Portrait (width, height) in mm. Accepts "A4", "A3" or "<w>x<h>" in cm, e.g. "50x70"."""
    if size in PAPER_MM:
        return PAPER_MM[size]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)", size.strip())
    if not m:
        raise ValueError(f'Unknown size {size!r}: use "A4", "A3" or "<w>x<h>" in cm, e.g. "50x70"')
    w, h = (float(g) * 10 for g in m.groups())
    return min(w, h), max(w, h)


def default_dpi(size: str) -> int:
    return 300 if size in PAPER_MM else 150  # big formats are viewed from further away


def choose_orientation(photo_size: tuple[int, int], setting: str = "auto") -> str:
    if setting in ("portrait", "landscape"):
        return setting
    w, h = photo_size
    return "landscape" if w / h > 1.05 else "portrait"  # square counts as portrait


# ---------- effects ----------

def vintage(photo: Image.Image, saturation, contrast, warmth, fade) -> Image.Image:
    """Faded, slightly warm film look."""
    photo = ImageEnhance.Color(photo).enhance(saturation)
    photo = ImageEnhance.Contrast(photo).enhance(contrast)
    a = np.asarray(photo).astype(np.float32)
    a[..., 0] *= 1 + warmth          # more red
    a[..., 2] *= 1 - warmth          # less blue
    a = a * (1 - fade) + 255 * fade  # lift the blacks
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def add_grain(img: Image.Image, strength: float, seed: int = 0) -> Image.Image:
    """Monochrome film grain over the whole poster (chunked to keep memory low)."""
    if strength <= 0:
        return img
    rng = np.random.default_rng(seed)
    a = np.array(img)
    for y in range(0, a.shape[0], 512):
        chunk = a[y:y + 512].astype(np.float32)
        chunk += rng.standard_normal(chunk.shape[:2], dtype=np.float32)[..., None] * strength
        a[y:y + 512] = np.clip(chunk, 0, 255)
    return Image.fromarray(a)


def _noise(rng, W: int, H: int, scale: int) -> np.ndarray:
    """Smooth noise: random values on a coarse grid, upsampled to W x H."""
    if scale <= 1:
        return rng.standard_normal((H, W), dtype=np.float32)
    n = rng.standard_normal((max(2, H // scale), max(2, W // scale)), dtype=np.float32)
    return np.asarray(Image.fromarray(n).resize((W, H), Image.BICUBIC))


def make_paper(W: int, H: int, color, u: float, strength: float = 1.0, creases: int = 3,
               texture_img: Image.Image | None = None, seed: int = 0) -> Image.Image:
    """Paper: flat colour modulated by fibres/speckle noise, soft creases, or a scanned texture."""
    rng = np.random.default_rng(seed)
    lum = np.zeros((H, W), np.float32)
    for k, amp in ((64, 0.008), (16, 0.005), (4, 0.004), (1, 0.007)):
        lum += amp * _noise(rng, W, H, max(1, round(k * u / 3.7)))
    if creases:
        cw, ch = max(W // 4, 2), max(H // 4, 2)
        crease = Image.new("L", (cw, ch), 0)
        cd = ImageDraw.Draw(crease)
        for _ in range(creases):
            p0 = (rng.uniform(0, cw), rng.uniform(0, ch))
            ang = rng.uniform(0, np.pi)
            L = max(cw, ch) * 1.5
            p1 = (p0[0] + L * np.cos(ang), p0[1] + L * np.sin(ang))
            p2 = (p0[0] - L * np.cos(ang), p0[1] - L * np.sin(ang))
            cd.line([p1, p2], fill=255, width=max(1, round(1.2 * u / 4)))
        crease = np.asarray(crease.filter(ImageFilter.GaussianBlur(max(1.0, 1.5 * u / 4))),
                            dtype=np.float32) / 255
        shifted = np.roll(crease, max(2, round(2 * u / 4)), axis=1)
        c = crease * -0.05 + shifted * 0.035   # dark fold next to a highlight
        lum += np.asarray(Image.fromarray(c).resize((W, H), Image.BICUBIC))
    if texture_img is not None:
        g = np.asarray(ImageOps.fit(texture_img.convert("L"), (W, H), Image.LANCZOS), np.float32)
        lum += (g / max(g.mean(), 1) - 1) * 0.8
    lum *= strength
    base = np.array(color, np.float32)
    out = np.empty((H, W, 3), np.uint8)
    for y in range(0, H, 512):
        out[y:y + 512] = np.clip(base * (1 + lum[y:y + 512, :, None]), 0, 255)
    return Image.fromarray(out)


# ---------- codes ----------

def make_qr(url: str, size: int) -> Image.Image:
    """Black-on-white QR with a quiet zone; NEAREST keeps the modules sharp."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.NEAREST)


SPOTIFY_RE = re.compile(
    r"(?:spotify:|open\.spotify\.com/(?:intl-[a-z-]+/)?)"
    r"(track|album|playlist|artist|show|episode)[:/]([A-Za-z0-9]{22})")


def parse_spotify(ref: str) -> str:
    """Spotify link or URI -> canonical URI like 'spotify:track:<id>'."""
    m = SPOTIFY_RE.search(ref)
    if not m:
        raise ValueError(f"Not a Spotify link or URI: {ref!r}")
    return f"spotify:{m.group(1)}:{m.group(2)}"


def spotify_code(ref: str, cache_dir: Path) -> Image.Image:
    """The Spotify code as a greyscale image (dark bars on white). Downloaded once, then cached."""
    uri = parse_spotify(ref)
    path = cache_dir / (uri.replace(":", "_") + ".png")
    if not path.exists():
        url = f"https://scannables.scdn.co/uri/plain/png/ffffff/black/640/{uri}"
        req = urllib.request.Request(url, headers={"User-Agent": "poster-maker"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if not data.startswith(b"\x89PNG"):
            raise RuntimeError(f"Spotify did not return a PNG for {uri}")
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return Image.open(path).convert("L")


# ---------- drawing helpers ----------

def ink_bbox(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int, int, int]:
    """Real ink bounds (left, top, right, bottom) relative to the draw origin, anchor 'la'.
    getbbox() reports advance width, which includes side bearings, so measure the pixels."""
    pad = font.size
    w = int(font.getlength(text)) + 2 * pad
    canvas = Image.new("L", (w, font.size * 2 + 2 * pad), 0)
    ImageDraw.Draw(canvas).text((pad, pad), text, font=font, fill=255)
    l, t, r, b = canvas.getbbox()
    return l - pad, t - pad, r - pad, b - pad


def fit_font(text: str, font_path: str, target_w: float) -> ImageFont.FreeTypeFont:
    """Largest font whose ink width is <= target_w."""
    lo, hi = 10, max(20, int(target_w * 2))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        l, _, r, _ = ink_bbox(ImageFont.truetype(font_path, mid), text)
        if r - l <= target_w:
            lo = mid
        else:
            hi = mid - 1
    return ImageFont.truetype(font_path, lo)


def crop_mark(draw, cx, cy, arm, width, color):
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=color, width=width)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=color, width=width)


def shrink_to_fit(draw, texts, font_path, size, max_w):
    """Font of `size`, reduced until every text is <= max_w wide."""
    while size > 8:
        f = ImageFont.truetype(font_path, size)
        if all(draw.textlength(t, font=f) <= max_w for t in texts):
            return f
        size -= 1
    return ImageFont.truetype(font_path, 8)


# ---------- layout ----------

def render_gallery(cfg: dict, base: Path) -> Image.Image:
    p, fonts = cfg["poster"], cfg["fonts"]
    eff = {**EFFECTS, **cfg.get("effects", {})}
    ink, paper = hex_rgb(p["ink"]), hex_rgb(p["paper"])

    photo = ImageOps.exif_transpose(Image.open(base / p["photo"])).convert("RGB")
    orient = choose_orientation(photo.size, p.get("orientation", "auto"))
    w_mm, h_mm = paper_mm(p["size"])
    if orient == "landscape":
        w_mm, h_mm = h_mm, w_mm
    dpi = p.get("dpi") or default_dpi(p["size"])
    W, H = mm_to_px(w_mm, dpi), mm_to_px(h_mm, dpi)
    u = min(W, H) / DESIGN_W              # design px -> print px
    s = lambda v: round(v * u)

    tex = Image.open(base / p["paper_texture"]) if p.get("paper_texture") else None
    poster = make_paper(W, H, paper, u, eff["texture"], eff["creases"], tex)
    d = ImageDraw.Draw(poster)

    m = s(40)                             # page margin
    cw = W - 2 * m                        # content width
    for cx in (m, W - m):                 # crop marks, top corners
        crop_mark(d, cx, m, s(14), max(2, s(1.4)), ink)

    # footer: info columns (left) + scan code (right), bottom aligned
    short = min(W, H)
    if p.get("spotify"):
        code = spotify_code(p["spotify"], base / "assets" / "spotify")
        code_w = round(0.20 * short)
        code_h = round(code_w * code.height / code.width)
        code = ImageOps.invert(code.resize((code_w, code_h), Image.LANCZOS))
        code = ImageOps.autocontrast(code)          # alpha: 255 where the bars are
    elif p.get("url"):
        code_w = code_h = round(0.12 * short)
        code = make_qr(p["url"], code_w)
    else:
        code, code_w, code_h = None, 0, 0

    info = p.get("info", [])
    info_h = s(33) if info else 0
    fh = max(info_h, code_h)
    foot_bottom = H - m
    photo_bottom = foot_bottom - fh - s(16)

    if info:
        area = cw - code_w - (s(24) if code else 0)
        col_w = area / len(info)
        labels = [f'{i["label"]} -' for i in info]
        label_f = shrink_to_fit(d, labels, str(base / fonts["label"]), s(13), col_w - s(8))
        mono_f = shrink_to_fit(d, [i["value"] for i in info], str(base / fonts["mono"]), s(12), col_w - s(8))
        y0 = foot_bottom - info_h
        for i, item in enumerate(info):
            x = m + i * col_w
            d.text((x, y0), labels[i], font=label_f, fill=ink)
            d.text((x, y0 + s(19)), item["value"], font=mono_f, fill=ink)

    if code is not None:
        pos = (W - m - code_w, foot_bottom - code_h)
        if code.mode == "L":
            poster.paste(Image.new("RGB", code.size, ink), pos, code)
        else:
            poster.paste(code, pos)

    # title + photo block
    title = p["title"]
    show_title = p.get("show_title", True)
    if show_title:
        title_f = fit_font(title, str(base / fonts["title"]), cw * p.get("title_width", 1.0))
        tl, tt, tr, _ = ink_bbox(title_f, title)
        ascent = title_f.getmetrics()[0]
        hb = ascent - tt                              # ink top -> baseline
    else:
        hb = 0                                        # no title: just the whole photo
    top_min = m + s(48)                               # keep clear of the crop marks
    avail = photo_bottom - (top_min + hb)             # room for the block below the baseline
    if avail <= 0:
        raise ValueError("Title too tall for this page: lower title_width or use a larger page")
    ideal = cw * photo.height / photo.width - hb      # block height that crops nothing
    bh = round(min(max(ideal, 0.3 * cw), avail))
    if show_title:
        baseline = photo_bottom - bh                  # block sits on the footer, title above it
    else:
        baseline = top_min + (avail - bh) // 2        # photo centred in the free space
    y_top = baseline - hb
    full_h = hb + bh

    fx, fy = p.get("focus", (0.5, 0.5))
    fitted = ImageOps.fit(photo, (cw, full_h), Image.LANCZOS, centering=(fx, fy))
    scale = max(cw / photo.width, full_h / photo.height)
    ppi = dpi / scale
    min_ppi = 150 if p["size"] in PAPER_MM else 100
    if ppi < min_ppi:
        print(f"warning: photo is only ~{ppi:.0f} ppi at {p['size']} (aim for >= {min_ppi}); "
              "it may print soft", file=sys.stderr)
    fitted = vintage(fitted, eff["saturation"], eff["contrast"], eff["warmth"], eff["fade"])

    mask = Image.new("L", (cw, full_h), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle([0, hb, cw, full_h], fill=255)       # the photo block
    if show_title:
        md.text((-tl, -tt), title, font=title_f, fill=255)  # the title: photo continues up through it
    poster.paste(fitted, (m, y_top), mask)

    return add_grain(poster, eff["grain"])


LAYOUTS = {"gallery": render_gallery}


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="Render a retro poster from a TOML config.")
    ap.add_argument("config", nargs="?", default="config/poster.toml")
    ap.add_argument("-o", "--output", help="output file (default: output/<title>_<size>_<orientation>.png)")
    ap.add_argument("--photo")
    ap.add_argument("--size")
    ap.add_argument("--dpi", type=int)
    ap.add_argument("--orientation", choices=["auto", "portrait", "landscape"])
    ap.add_argument("--no-title", action="store_true", help="hide the giant title, show the whole photo")
    args = ap.parse_args(argv)

    config_path = Path(args.config)
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.resolve().parent.parent  # project root (config/ is one level down)
    p = cfg["poster"]
    for key in ("photo", "size", "dpi", "orientation"):
        if getattr(args, key) is not None:
            p[key] = getattr(args, key)

    if args.no_title:
        p["show_title"] = False

    img = LAYOUTS[p.get("layout", "gallery")](cfg, base)
    dpi = p.get("dpi") or default_dpi(p["size"])
    if args.output:
        out = Path(args.output)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-") or "poster"
        orient = "landscape" if img.width > img.height else "portrait"
        out = base / "output" / f'{slug}_{p["size"]}_{orient}.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, dpi=(dpi, dpi))
    print(f"Saved {out}  ({img.width}x{img.height} px, {dpi} DPI)")


if __name__ == "__main__":
    main()
