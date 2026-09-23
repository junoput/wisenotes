"""Uploads are judged by content; only webp and gif are ever stored or served as images."""

import io

import pytest
from PIL import Image

from app.services.image_processing import UnsupportedImage
from app.services.image_processing import process_uploaded_image


def _img(fmt, mode="RGB", size=(5, 3), frames=1):
    buf = io.BytesIO()
    im = Image.new(mode, size, "red")
    if frames > 1:
        im.save(
            buf,
            format=fmt,
            save_all=True,
            append_images=[Image.new(mode, size, "blue")] * (frames - 1),
        )
    else:
        im.save(buf, format=fmt)
    return buf.getvalue()


def test_raster_is_reencoded_to_webp_whatever_the_name_says():
    name, data, meta = process_uploaded_image("photo.exe", _img("PNG"))
    assert name.endswith(".webp") and meta.mime_type == "image/webp"
    assert Image.open(io.BytesIO(data)).format == "WEBP"
    assert meta.original_filename == "photo.exe" and meta.width == 5


def test_gif_is_kept_and_animation_detected():
    raw = _img("GIF", mode="P", frames=3)
    name, data, meta = process_uploaded_image("anim.png", raw)  # name lies; content wins
    assert name.endswith(".gif") and data == raw and meta.is_animated is True


@pytest.mark.parametrize(
    "name, body",
    [
        ("evil.svg", b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"),
        ("evil.png", b"<?xml version='1.0'?><svg/>"),
        ("evil.png", b"<svg/>"),
        ("page.html", b"<html><script>1</script></html>"),
        ("x.png", b"not an image at all"),
        ("empty.png", b""),
    ],
)
def test_svg_and_non_images_are_refused_by_content(name, body):
    with pytest.raises(UnsupportedImage):
        process_uploaded_image(name, body)


def test_upload_route_refuses_svg_and_serves_only_stored_types(client):
    client.post("/notes", data={"title": "Media"}, follow_redirects=False)
    note = client.get("/api/notes").json()[0]
    nid = note["id"]
    resp = client.post(
        f"/notes/{nid}/media/upload",
        files={"file": ("a.svg", b"<svg onload=alert(1)/>", "image/svg+xml")},
    )
    assert resp.status_code == 400 and "SVG" in resp.json()["detail"]
    ok = client.post(
        f"/notes/{nid}/media/upload",
        files={"file": ("a.bin", _img("PNG"), "application/octet-stream")},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    [stored] = client.get(f"/api/notes/{nid}/media/list").json()["media"]
    served = client.get(f"/api/notes/{nid}/media/{stored}")
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    assert "attachment" not in served.headers.get("content-disposition", "")


def test_stray_file_on_disk_is_never_rendered(client, service):
    client.post("/notes", data={"title": "Stray"}, follow_redirects=False)
    note = client.get("/api/notes").json()[0]
    # an older upload or a hand-copied file that bypassed the pipeline
    service.repo.save_media(note["name"], "old.svg", b"<svg onload=alert(1)/>")
    served = client.get(f"/api/notes/{note['id']}/media/old.svg")
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/octet-stream"
    assert served.headers["content-disposition"].startswith("attachment")
