from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from archsearch.api import create_app
from archsearch.corpus import load_corpus


class LocalAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(str(values["src"]))
        if tag == "link" and values.get("rel") == "stylesheet":
            self.assets.append(str(values["href"]))


def test_frontend_assets_are_served_locally_without_a_model(tmp_path: Path) -> None:
    with TestClient(create_app(home=tmp_path, sites=load_corpus()[:1])) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "考古图志" in page.text
        assets = LocalAssets()
        assets.feed(page.text)
        assert assets.assets
        for uri in assets.assets:
            assert uri.startswith("/static/")
            response = client.get(uri)
            assert response.status_code == 200
            assert response.content
        assert client.get("/api/status").json()["semantic"]["ready"] is False
        assert client.get("/static/vendor/leaflet/images/marker-icon.png").status_code == 200
