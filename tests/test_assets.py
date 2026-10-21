"""20261021-011: the app's own static files are versioned from their content."""

import re
import shutil

from app import assets


def _local_assets(html):
    return re.findall(r'(?:href|src)="(/static/[^"]+)"', html)


def test_every_own_stylesheet_and_script_carries_the_content_version(client):
    html = client.get("/").text
    urls = _local_assets(html)
    assert len(urls) >= 3, urls  # premise: style.css, init-layout.js, app.js
    own = [u for u in urls if not u.startswith("/static/vendor/")]
    assert {u.split("?")[0] for u in own} >= {
        "/static/css/style.css",
        "/static/js/init-layout.js",
        "/static/js/app.js",
    }
    assert re.fullmatch(r"[0-9a-f]{12}", assets.ASSET_VERSION)
    for u in own:
        assert u.endswith(f"?v={assets.ASSET_VERSION}"), u


def test_the_version_follows_any_own_file_and_ignores_vendor(tmp_path, monkeypatch):
    shutil.copytree(assets.STATIC, tmp_path / "static")
    monkeypatch.setattr(assets, "STATIC", tmp_path / "static")
    before = assets._version()
    assert assets._version() == before  # stable for the same files
    vendored = tmp_path / "static/vendor/htmx/htmx.min.js"
    vendored.write_text(vendored.read_text() + "\n")
    assert assets._version() == before
    module = tmp_path / "static/js/drag-drop.js"  # imported by app.js, never in base.html
    module.write_text(module.read_text() + "\n")
    assert assets._version() != before


def test_static_files_are_revalidated_not_guessed(client):
    resp = client.get("/static/js/drag-drop.js")
    assert resp.status_code == 200 and resp.headers["cache-control"] == "no-cache"
    again = client.get("/static/js/drag-drop.js", headers={"If-None-Match": resp.headers["etag"]})
    assert again.status_code == 304  # cheap when unchanged


def test_harness_control_a_page_is_not_given_the_static_header(client):
    assert "cache-control" not in client.get("/").headers
