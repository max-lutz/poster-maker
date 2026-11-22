# Retro Poster Generator: Python Project Handout

Turn your own photos into print-ready retro posters (paper texture, film grain, giant title, info row, crop marks and a QR code) with one command.

```
python poster.py config/poster.toml   →   output/retro_classic_A4.png  (2480 × 3508 px, 300 DPI)
```

---

## 1. What you'll learn

- Image compositing with **Pillow** (layers, text, pasting, resizing)
- Simple pixel maths with **NumPy** (grain, colour grading)
- Generating **QR codes** that scan reliably in print
- Thinking in **print units** (mm → px at a given DPI)
- Keeping design choices in a **config file** instead of hard-coding them

**Prerequisites:** Python 3.11+ (for the built-in `tomllib`), basic Python (functions, dicts, loops).

---

## 2. Project structure

```
retro-posters/
├── poster.py            # the generator (start here)
├── requirements.txt
├── config/
│   └── poster.toml      # one file per poster you want to make
├── fonts/               # .ttf files (see section 4)
├── photos/              # your input photos
└── output/              # generated posters (created automatically)
```

---

## 3. Setup

```bash
mkdir retro-posters && cd retro-posters
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
mkdir config fonts photos output
```

**requirements.txt**

```
pillow>=10.0
numpy>=1.26
qrcode>=7.4
```

---

## 4. Fonts

Download these free Google Fonts (open licence, fine for posters) and copy the **static** `.ttf` files into `fonts/`:

| Role | Font | File to use |
|---|---|---|
| Big title | Jost | `Jost-ExtraBold.ttf` (in the `static/` folder of the download) |
| Labels | Inter | the Bold static file, renamed `Inter-Bold.ttf` |
| Values | IBM Plex Mono | `IBMPlexMono-Regular.ttf` |

Any font works. Just update the paths in the config. Geometric sans-serifs (Futura, Jost, Outfit) give the most "retro" feel.

---

## 5. Key concepts

### 5.1 Print size → pixels

```
pixels = mm / 25.4 × DPI
```

| Paper | mm | px at 300 DPI |
|---|---|---|
| A4 | 210 × 297 | 2480 × 3508 |
| A3 | 297 × 420 | 3508 × 4961 |

**Trick used in the code:** the layout is designed on a page **794 px wide** (A4 at 96 DPI, i.e. screen size). Every position is multiplied by a scale factor `u = W / 794`. The same layout then works at A4 or A3 and at any DPI.

### 5.2 Layer order (painter's algorithm)

Each step paints over the previous one:

1. Paper background colour
2. Crop marks + info row
3. Photo (cropped to fit, colour-graded)
4. Title, **overlapping the top of the photo**
5. Tagline + QR code (on a white box so it scans)
6. Grain over **everything**, which ties all layers together

### 5.3 The "vintage" look

- Lower saturation and contrast slightly
- Push red up and blue down (warmth)
- **Lift the blacks** (`a * 0.94 + 255 * 0.06`): nothing is pure black, which gives the faded-print feel

### 5.4 QR codes that actually scan

- Error correction **M** (or **H** if you'll put a logo on it)
- Resize with `Image.NEAREST`, never smooth resampling, so the squares stay sharp
- Keep a **white quiet zone** around it
- Minimum ~2 × 2 cm when printed
- Always test with your phone before printing a batch

---

## 6. The config file

**config/poster.toml**

```toml
[poster]
layout  = "classic"
size    = "A4"          # "A4" or "A3"
dpi     = 300
title   = "RETRO"
tagline = "Take a Trip to the Past – Scan Me"
url     = "https://example.com"
photo   = "photos/my_photo.jpg"
paper   = "#e9e6df"
ink     = "#1d1d1f"
accent  = "#5b86c9"
grain   = 14

info = [
  { label = "Title",   value = "Retro" },
  { label = "Date",    value = "22/11/26" },
  { label = "Place",   value = "Paris" },
  { label = "Photo",   value = "Max" },
  { label = "Edition", value = "No. 001" },
]

[fonts]
title = "fonts/Jost-ExtraBold.ttf"
label = "fonts/Inter-Bold.ttf"
mono  = "fonts/IBMPlexMono-Regular.ttf"
```

Accent colours that work well on this paper: blue `#5b86c9`, rust `#d1603d`, green `#2f6b4f`, black `#1d1d1f`.

---

## 7. Starter code: `poster.py`

```python
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
    photo = Image.open(base / p["photo"]).convert("RGB")
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
```

### Run it

```bash
python poster.py config/poster.toml
```

Open the image in `output/`, zoom to 100 %, scan the QR code with your phone, then tweak the config and run again.

---

## 8. Exercises (in suggested order)

1. **Make it yours:** change the title, accent colour and info row. Try `size = "A3"` and check that nothing moves.
2. **Tune the look:** expose `saturation`, `warmth` and `fade` in the config (`[effects]` section) instead of hard-coding them.
3. **Paper texture:** blend a scanned paper texture (`photos/paper.jpg`) with the background, using `Image.blend` or a multiply with NumPy.
4. **New layout, "Split":** photo across the top half, title below, info grid on the left, QR code in a framed box on the right. Add `render_split` to `LAYOUTS`.
5. **New layout, "Ticket stub":** framed photo with the title in cream inside it, a dashed perforation line (draw short line segments in a loop), and a stub with details and the QR code.
6. **Command line:** replace `sys.argv` with `argparse` (`--size A3`, `--layout split`, `--photo ...`) so options override the config.
7. **Batch mode:** render every `.toml` in `config/`, or one poster per photo in `photos/`.
8. **Print export:** save a PDF as well (`img.save("x.pdf", resolution=300)`) and optionally add 3 mm **bleed** on each side for print shops.
9. **Test it:** use `pyzbar` to decode the QR code from the output image and assert it equals `url`.
10. **Refactor:** split into a package (`effects.py`, `layouts/`, `cli.py`) once you have 2–3 layouts.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `OSError: cannot open resource` | Font path is wrong. Check the file name in `fonts/` matches the config. |
| `ModuleNotFoundError: tomllib` | You're on Python < 3.11. Upgrade, or `pip install tomli` and `import tomli as tomllib`. |
| Title too high/low | Fonts have different internal spacing. Adjust the `s(492)` value or the `top_offset` logic. |
| Photo looks soft when printed | Your photo is too small. Aim for ≥ 2000 px wide for A4, ≥ 3000 px for A3, or upscale it first (e.g. Upscayl). |
| QR code won't scan | Make it bigger, keep the white margin, and make sure it was resized with `NEAREST`. |
| Phone photo appears rotated | Add `photo = ImageOps.exif_transpose(photo)` right after `Image.open`. |
| Colours look different on paper | Screens are RGB and printers CMYK. Print a small test first, and avoid very saturated blues. |

---

## 10. Useful references

- Pillow docs: https://pillow.readthedocs.io
- `qrcode` package: https://pypi.org/project/qrcode/
- Google Fonts: https://fonts.google.com
- NumPy basics: https://numpy.org/doc/stable/user/absolute_beginners.html
