"""Manual CDN fallback security checks and smoke tests."""
import io
import zipfile
import pytest
import manual_media
import server


@pytest.mark.parametrize("url", [
    "https://evil.example.org/photo.jpg",
    "http://x.fbcdn.net/a.jpg",
    "https://fbcdn.net.evil.com/photo.jpg",
    "https://user:pass@x.fbcdn.net/a.jpg",
    "https://x.fbcdn.net:443/a.jpg",
])
def test_rejects_untrusted_url(url):
    with pytest.raises(ValueError):
        manual_media.validate_url(url)


def test_preserve_query():
    url = "https://x.cdninstagram.com/a.jpg?oh=signed&oe=expiry"
    assert manual_media.validate_url(url + "#fragment") == url


def test_manual_download(monkeypatch):
    monkeypatch.setattr(manual_media, "fetch_image",
                        lambda url: (b"\xff\xd8\xffdata", ".jpg", ""))
    response = server.app.test_client().post(
        "/api/download-direct", json={"image_urls": ["https://x.fbcdn.net/a.jpg"]})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ["image_01.jpg"]


def test_rejects_html():
    assert manual_media.sniff_extension(b"<html>not an image</html>") is None
