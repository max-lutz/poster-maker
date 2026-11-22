from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

import poster

ROOT = Path(__file__).resolve().parent.parent
TRACK = "4cOdK2wGLETKBW3PvgPWqT"


def make_cfg(photo_name: str = "photo.jpg", **overrides) -> dict:
    p = dict(size="A4", dpi=100, title="Retro", photo=photo_name, paper="#e9e6df", ink="#1d1d1f",
             url="https://example.com", info=[{"label": "Date", "value": "22/11/26"}])
    p.update(overrides)
    return {"poster": p, "effects": {"grain": 0, "texture": 0, "creases": 0},
            "fonts": {"title": str(ROOT / "fonts/Jost-ExtraBold.ttf"),
                      "label": str(ROOT / "fonts/Inter-Bold.ttf"),
                      "mono": str(ROOT / "fonts/IBMPlexMono-Regular.ttf")}}


def save_photo(tmp_path: Path, size: tuple[int, int]) -> None:
    rng = np.random.default_rng(1)
    Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)).save(tmp_path / "photo.jpg")


def test_paper_sizes():
    assert poster.paper_mm("A3") == (297, 420)
    assert poster.paper_mm("50x70") == (500, 700)
    assert poster.paper_mm("70x50") == (500, 700)  # always portrait order
    with pytest.raises(ValueError):
        poster.paper_mm("big")


def test_default_dpi():
    assert poster.default_dpi("A3") == 300
    assert poster.default_dpi("50x70") == 150


def test_orientation():
    assert poster.choose_orientation((3000, 2000)) == "landscape"
    assert poster.choose_orientation((2000, 3000)) == "portrait"
    assert poster.choose_orientation((2000, 2000)) == "portrait"   # square
    assert poster.choose_orientation((3000, 2000), "portrait") == "portrait"


def test_parse_spotify():
    uri = f"spotify:track:{TRACK}"
    assert poster.parse_spotify(f"https://open.spotify.com/track/{TRACK}?si=abc") == uri
    assert poster.parse_spotify(f"https://open.spotify.com/intl-fr/track/{TRACK}") == uri
    assert poster.parse_spotify(uri) == uri
    with pytest.raises(ValueError):
        poster.parse_spotify("https://example.com/nope")


@pytest.mark.parametrize("photo_size,expected", [((600, 800), (827, 1169)), ((800, 600), (1169, 827))])
def test_page_follows_photo_orientation(tmp_path, photo_size, expected):
    save_photo(tmp_path, photo_size)
    img = poster.render_gallery(make_cfg(), tmp_path)
    assert img.size == expected


def test_50x70_size(tmp_path):
    save_photo(tmp_path, (600, 800))
    img = poster.render_gallery(make_cfg(size="50x70", dpi=20), tmp_path)
    assert img.size == (poster.mm_to_px(500, 20), poster.mm_to_px(700, 20))


def test_qr_code_decodes(tmp_path):
    save_photo(tmp_path, (600, 800))
    img = poster.render_gallery(make_cfg(dpi=200, url="https://example.com/retro"), tmp_path)
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
    assert text == "https://example.com/retro"


def test_spotify_code_uses_cache(tmp_path, monkeypatch):
    """With a cached code image the renderer must not touch the network."""
    save_photo(tmp_path, (600, 800))
    cache = tmp_path / "assets" / "spotify"
    cache.mkdir(parents=True)
    Image.new("L", (640, 160), 255).save(cache / f"spotify_track_{TRACK}.png")

    def no_network(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(poster.urllib.request, "urlopen", no_network)
    img = poster.render_gallery(make_cfg(spotify=f"https://open.spotify.com/track/{TRACK}"), tmp_path)
    assert img.size == (827, 1169)


def test_title_too_tall_is_an_error(tmp_path):
    save_photo(tmp_path, (800, 600))
    cfg = make_cfg(title="il")
    with pytest.raises(ValueError):
        poster.render_gallery(cfg, tmp_path)


def test_no_title_shows_whole_photo(tmp_path):
    """Without the title the block is exactly as tall as the photo's shape needs, so nothing is cropped."""
    save_photo(tmp_path, (600, 800))
    with_title = poster.render_gallery(make_cfg(), tmp_path)
    without = poster.render_gallery(make_cfg(show_title=False), tmp_path)
    assert without.size == with_title.size
    assert np.asarray(without).std() > 0 and not np.array_equal(np.asarray(with_title), np.asarray(without))
