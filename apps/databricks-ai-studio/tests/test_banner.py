from html.parser import HTMLParser

from ui import banner


class Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.text = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def parse(h):
    c = Collect()
    c.feed(h)
    return c


def test_drawn_banner_by_default_and_escaped():
    h = banner.banner_html("Discovery", "Agents <IA> & métiers")
    c = parse(h)
    classes = [a.get("class") for _, a in c.tags]
    assert "ais-hero dsc-banner" in classes and "dsc-banner-train" in classes
    art = next(a for _, a in c.tags if a.get("class") == "dsc-banner-art")
    assert "data:image/svg+xml;base64," in art["style"]
    assert "Agents <IA> & métiers" in "".join(c.text) and "<IA>" not in h


def test_full_banner_image_takes_precedence(tmp_path, monkeypatch):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "hero_full.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(banner, "ASSETS", tmp_path)
    banner._uri.cache_clear()
    c = parse(banner.banner_html("Discovery", "x"))
    img = [a for t, a in c.tags if t == "img"]
    assert len(img) == 1 and img[0]["src"].startswith("data:image/png;base64,") and "Discovery" in img[0]["alt"]


def test_photo_replaces_drawn_art(tmp_path, monkeypatch):
    (tmp_path / "img").mkdir(); (tmp_path / "icons").mkdir()
    (tmp_path / "img" / "hero_photo.jpg").write_bytes(b"\xff\xd8fake")
    (tmp_path / "icons" / "train_line.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    monkeypatch.setattr(banner, "ASSETS", tmp_path)
    banner._uri.cache_clear()
    c = parse(banner.banner_html("Discovery", "x"))
    art = next(a for _, a in c.tags if a.get("class") == "dsc-banner-art")
    assert "data:image/jpeg;base64," in art["style"]
