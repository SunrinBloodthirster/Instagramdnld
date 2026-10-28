"""Minimal Instagram public-photo download backend.

The service deliberately does not accept authentication credentials or cookies.
It only passes validated public Instagram post URLs to gallery-dl.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile

from flask import Flask, jsonify, request, send_file

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(BASE_DIR / "docs"), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
app.json.ensure_ascii = False

ALLOWED_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
POST_PATH = re.compile(r"^/(p|reel|tv)/([A-Za-z0-9_-]{5,32})/?$")
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".gif"}
MAX_POSTS = 3
MAX_PHOTOS = 60
MAX_ZIP_BYTES = 80 * 1024 * 1024
REQUEST_TIMEOUT = 30
REQUESTS_PER_WINDOW = 8
WINDOW_SECONDS = 15 * 60
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()}
ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "")
_jobs = threading.BoundedSemaphore(2)
_rate_lock = threading.Lock()
_rates: dict[str, deque[float]] = defaultdict(deque)


@app.after_request
def add_headers(response):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-App-Key"
        response.headers["Access-Control-Expose-Headers"] = "X-Downloaded-Posts, X-Failed-Posts, X-Photo-Count"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def normalize_post_url(raw: str) -> tuple[str, str]:
    """Allowlisted host + path, ignore query parameters and fragments."""
    if not isinstance(raw, str) or len(raw) > 400:
        raise ValueError("게시물 주소가 너무 길거나 올바르지 않습니다.")
    try:
        parsed = urlsplit(raw.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("올바른 인스타그램 주소가 아닙니다.") from exc
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS or port is not None:
        raise ValueError("https://www.instagram.com/으로 시작하는 게시물 링크만 지원합니다.")
    if parsed.username or parsed.password:
        raise ValueError("사용자 정보가 포함된 URL은 사용할 수 없습니다.")
    match = POST_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("게시물(/p/), 릴스(/reel/), TV(/tv/)의 개별 링크만 지원합니다.")
    content_type, shortcode = match.groups()
    return f"https://www.instagram.com/{content_type}/{shortcode}/", shortcode


def rate_limited(address: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        history = _rates[address]
        while history and now - history[0] > WINDOW_SECONDS:
            history.popleft()
        if len(history) >= REQUESTS_PER_WINDOW:
            return True
        history.append(now)
    return False


def classify_error(message: str) -> str:
    lower = message.lower()
    if "429" in lower or "rate limit" in lower:
        return "인스타그램 요청 제한에 걸렸습니다. 잠시 뒤 다시 시도해 주세요."
    if "login" in lower or "authentication" in lower or "401" in lower or "403" in lower:
        return "인스타그램에서 로그인을 요구하거나 접근을 제한했습니다. 공개 게시물도 제한될 수 있습니다."
    if "missing_required_variable_value" in lower or "keyerror" in lower or "failed to load api data" in lower:
        return "인스타그램 데이터 요청 방식 변경으로 사진 추출에 실패했습니다. 직접 이미지 주소 저장을 이용해 주세요."
    if "404" in lower or "not found" in lower:
        return "게시물을 찾지 못했습니다. 주소 또는 공개 상태를 확인해 주세요."
    return "사진을 가져오지 못했습니다. 비공개 게시물이거나 인스타그램의 접근 제한일 수 있습니다."


def download_photos(url: str, destination: Path) -> tuple[list[Path], str]:
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "gallery_dl",
        "--config-ignore", "--no-input", "--quiet",
        "--directory", str(destination),
        "--filter", "extension in ('jpg', 'jpeg', 'png', 'webp', 'avif', 'heic', 'gif')",
        "--range", "1-20",
        "--filesize-max", "18M",
        "--retries", "0", "--http-timeout", "10",
        url,
    ]
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=REQUEST_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        completed = None
        print(f"[extractor] TIMEOUT duration_s={time.monotonic()-started:.1f}", flush=True)
    except OSError:
        print("[extractor] ENGINE_START_ERROR", flush=True)
        return [], "서버의 다운로드 엔진을 실행하지 못했습니다."

    photos = sorted(
        (p for p in destination.rglob("*") if p.is_file() and p.suffix.lower() in PHOTO_TYPES),
        key=lambda p: str(p),
    )
    if timed_out:
        return photos[:20], "게시물 추출 시간이 초과되었습니다. 인스타그램 접속 지연 또는 서버 접근 제한일 수 있습니다."
    if not photos:
        stderr = (completed.stderr or "")[-2000:]
        # Avoid logging signed URLs or cookies.
        if "login" in stderr.lower() or "403" in stderr:
            print("[extractor] ACCESS_RESTRICTED", flush=True)
        elif "429" in stderr:
            print("[extractor] RATE_LIMITED", flush=True)
        elif "missing_required_variable_value" in stderr.lower():
            print("[extractor] API_CHANGED", flush=True)
        else:
            print(f"[extractor] NO_MEDIA: exit={completed.returncode}", flush=True)
        return [], classify_error(stderr)
    print(f"[extractor] DONE duration_s={time.monotonic()-started:.1f} photo_count={len(photos)}", flush=True)
    return photos[:20], ""


from manual_media import register_manual_routes
register_manual_routes(app, ACCESS_KEY, rate_limited, _jobs)


@app.get("/")
def home():
    return app.send_static_file("index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True, engine="gallery-dl", access_key_required=bool(ACCESS_KEY))


@app.route("/api/download", methods=["POST", "OPTIONS"])
def download():
    if request.method == "OPTIONS":
        return ("", 204)
    if ACCESS_KEY and request.headers.get("X-App-Key") != ACCESS_KEY:
        return jsonify(error="서버 접근 키가 필요하거나 일치하지 않습니다."), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="요청 형식이 올바르지 않습니다."), 400

    provided = data.get("urls")
    if not isinstance(provided, list) or not (1 <= len(provided) <= MAX_POSTS):
        return jsonify(error=f"한 번에 1~{MAX_POSTS}개의 게시물 링크를 입력해 주세요."), 400

    posts: list[tuple[str, str]] = []
    seen: set[str] = set()
    try:
        for link in provided:
            url, code = normalize_post_url(link)
            if url not in seen:
                posts.append((url, code))
                seen.add(url)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    # A simple per-process safeguard for a small personal-use application.
    if rate_limited(request.remote_addr or "unknown"):
        return jsonify(error="요청 횟수가 많습니다. 15분 후 다시 시도해 주세요."), 429
    if not _jobs.acquire(blocking=False):
        return jsonify(error="현재 다른 다운로드를 처리 중입니다. 잠시 뒤 다시 시도해 주세요."), 503

    try:
        buffer = io.BytesIO()
        downloaded = 0
        failed = 0
        photo_count = 0
        failures: list[str] = []
        total_bytes = 0
        with tempfile.TemporaryDirectory(prefix="ig-photo-") as temporary:
            root = Path(temporary)
            with ZipFile(buffer, "w", compression=ZIP_STORED, allowZip64=False) as archive:
                for url, shortcode in posts:
                    dest = root / shortcode
                    photos, error = download_photos(url, dest)
                    if not photos:
                        failed += 1
                        failures.append(f"{shortcode}: {error}")
                        continue
                    downloaded += 1
                    if error:
                        failed += 1
                        failures.append(f"{shortcode}: {error} (일부 사진은 저장됨)")
                    for index, photo in enumerate(photos, start=1):
                        size = photo.stat().st_size
                        if total_bytes + size > MAX_ZIP_BYTES or photo_count >= MAX_PHOTOS:
                            return jsonify(error="사진의 총용량이 서버 제한(80MB)을 초과했습니다. 게시물 수를 줄여 주세요."), 413
                        total_bytes += size
                        photo_count += 1
                        archive.write(photo, arcname=f"{shortcode}/{index:02d}{photo.suffix.lower()}")
                if failures:
                    summary = "가져오지 못한 게시물:\n" + "\n".join(failures) + "\n"
                    archive.writestr("download_report.txt", summary.encode("utf-8"))
        if downloaded == 0:
            error = failures[0].split(": ", 1)[-1] if failures else "사진이 없습니다."
            if "시간이 초과" in error or "시간 초과" in error:
                code = "EXTRACTION_TIMEOUT"
            elif "로그인" in error or "접근을 제한" in error:
                code = "ACCESS_RESTRICTED"
            else:
                code = "EXTRACTION_FAILED"
            status = 504 if code == "EXTRACTION_TIMEOUT" else 422
            return jsonify(error=error, code=code, hint="직접 이미지 주소 저장 기능을 이용해 주세요."), status
        buffer.seek(0)
        name = f"instagram_photos_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.zip"
        response = send_file(buffer, mimetype="application/zip", as_attachment=True, download_name=name)
        response.headers["X-Downloaded-Posts"] = str(downloaded)
        response.headers["X-Failed-Posts"] = str(failed)
        response.headers["X-Photo-Count"] = str(photo_count)
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        _jobs.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
