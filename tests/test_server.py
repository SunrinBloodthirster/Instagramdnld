import io
import zipfile
from pathlib import Path

import pytest

import server


@pytest.mark.parametrize("raw,canonical,shortcode", [
    ("https://www.instagram.com/p/C7abcD_123-/", "https://www.instagram.com/p/C7abcD_123-/", "C7abcD_123-"),
    ("https://instagram.com/p/ABC12345/?igsh=xyz", "https://www.instagram.com/p/ABC12345/", "ABC12345"),
    ("https://m.instagram.com/reel/AbCde0-1", "https://www.instagram.com/reel/AbCde0-1/", "AbCde0-1"),
])
def test_normalize_good(raw, canonical, shortcode):
    assert server.normalize_post_url(raw) == (canonical, shortcode)


@pytest.mark.parametrize("raw", [
    "https://evil.com/p/ABCDEFG/",
    "https://instagram.com.evil.org/p/ABCDEFG/",
    "http://www.instagram.com/p/ABCDEFG/",
    "https://www.instagram.com:443/p/ABCDEFG/",
    "https://www.instagram.com/username/",
    "https://www.instagram.com/p/ABC/",
    "https://hello:pass@www.instagram.com/p/ABCDEFG/",
    "https://www.instagram.com/p/ABCDEFG/../../",
])
def test_normalize_bad(raw):
    with pytest.raises(ValueError):
        server.normalize_post_url(raw)


def test_health():
    client = server.app.test_client()
    result = client.get("/api/health")
    assert result.status_code == 200
    assert result.get_json()["ok"] is True


def test_invalid_payload():
    client = server.app.test_client()
    assert client.post("/api/download", json={"urls": ["https://example.com/"]}).status_code == 400
    assert client.post("/api/download", json={"urls": []}).status_code == 400
    assert client.post("/api/download", json={"urls": ["x"] * 4}).status_code == 400


def test_download_zip(monkeypatch):
    def fake_download(url, destination):
        destination.mkdir(parents=True, exist_ok=True)
        images = [destination / "hello.jpg", destination / "world.png"]
        for i, file in enumerate(images):
            file.write_bytes(b"image" + bytes([i]))
        return images, ""

    monkeypatch.setattr(server, "download_photos", fake_download)
    client = server.app.test_client()
    response = client.post("/api/download", json={"urls": ["https://www.instagram.com/p/C7abcD_123-/"]})
    assert response.status_code == 200
    assert response.headers["X-Photo-Count"] == "2"
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert sorted(archive.namelist()) == ["C7abcD_123-/01.jpg", "C7abcD_123-/02.png"]


def test_no_real_download(monkeypatch):
    monkeypatch.setattr(server, "download_photos", lambda url, destination: ([], "접근 제한"))
    client = server.app.test_client()
    response = client.post("/api/download", json={"urls": ["https://www.instagram.com/p/C7abcD_123-/"]})
    assert response.status_code == 422
    assert "접근 제한" in response.get_json()["error"]


def test_extractor_timeout_yields_clear_error(monkeypatch, tmp_path):
    import subprocess
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=server.REQUEST_TIMEOUT)
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    photos, error = server.download_photos("https://www.instagram.com/p/Abcde12345/", tmp_path)
    assert photos == []
    assert "시간이 초과" in error
    assert server.REQUEST_TIMEOUT == 30


def test_extractor_timeout_salvages_images(monkeypatch, tmp_path):
    import subprocess
    def fake_run(*args, **kwargs):
        (tmp_path / "saved.jpg").write_bytes(b"jpg")
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=server.REQUEST_TIMEOUT)
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    photos, error = server.download_photos("https://www.instagram.com/p/Abcde12345/", tmp_path)
    assert len(photos) == 1
    assert "시간이 초과" in error


def test_timeout_http_status(monkeypatch):
    monkeypatch.setattr(server, "download_photos", lambda url, path: ([], "게시물 추출 시간이 초과되었습니다."))
    response = server.app.test_client().post("/api/download", json={
        "urls": ["https://www.instagram.com/p/Abcde12345/"]
    })
    assert response.status_code == 504
    assert response.get_json()["code"] == "EXTRACTION_TIMEOUT"
