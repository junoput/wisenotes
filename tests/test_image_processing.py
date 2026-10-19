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


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_allowed_formats_still_pass(fmt):
    _, _, meta = process_uploaded_image(f"x.{fmt.lower()}", _img(fmt))
    assert meta.mime_type == "image/webp"


@pytest.mark.parametrize("fmt", ["BMP", "TIFF", "PPM", "ICO"])
def test_formats_outside_the_allowlist_are_refused(fmt):
    # Pillow opens all of these; only PNG, JPEG, WebP and GIF may reach a decoder.
    with pytest.raises(UnsupportedImage):
        process_uploaded_image("x.png", _img(fmt))


def test_eps_never_reaches_a_decoder():
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"
    with pytest.raises(UnsupportedImage):
        process_uploaded_image("x.png", eps)


def test_pixel_cap_is_read_from_the_header(monkeypatch):
    monkeypatch.setattr("app.services.image_processing.MAX_PIXELS", 100 * 100)
    process_uploaded_image("ok.png", _img("PNG", size=(100, 100)))  # at the cap: accepted
    for fmt in ("PNG", "GIF"):
        with pytest.raises(UnsupportedImage, match="too large"):
            process_uploaded_image("big", _img(fmt, size=(101, 100)))


def test_default_pixel_cap_refuses_a_small_file_declaring_a_huge_image():
    # The reviewer's bomb: tiny on disk, 13000x13000 declared. Refused before decoding.
    big = _img("PNG", mode="1", size=(13000, 13000))
    assert len(big) < 100_000
    with pytest.raises(UnsupportedImage, match="too large"):
        process_uploaded_image("bomb.png", big)


def test_truncated_jpeg_is_refused_not_a_server_error():
    # Cut inside the scan data: verify() passes (it does not decode a JPEG's
    # pixels) and the decode raises OSError. A cut in the headers fails verify()
    # instead and would not exercise the decode path.
    jpeg = _img("JPEG", size=(64, 64))
    truncated = jpeg[:-10]
    with Image.open(io.BytesIO(truncated)) as probe:
        probe.verify()  # precondition: this file reaches the decoder
    with pytest.raises(UnsupportedImage):
        process_uploaded_image("cut.jpg", truncated)
