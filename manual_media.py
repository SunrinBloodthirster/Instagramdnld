"""Constrained direct image-URL fallback for Instagram CDN assets."""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile

import requests
from flask import jsonify, request, send_file

CDN_SUFFIXES = ("fbcdn.net", "cdninstagram.com")
MAX_IMAGE_BYTES = 18 * 1024 * 1024
MAX_ZIP_BYTES = 80 * 1024 * 1024


def validate_url(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError("이미지 URL이 너무 길거나 올바르지 않습니다.")
    try:
        parsed = urlsplit(raw.strip())
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise ValueError("이미지 URL을 확인해 주세요.") from exc
    if parsed.scheme != "https" or not host or port is not None or parsed.username or parsed.password:
        raise ValueError("HTTPS 이미지 URL만 허용됩니다.")
    if not any(host == suffix or host.endswith("." + suffix) for suffix in CDN_SUFFIXES):
        raise ValueError("Meta 이미지 CDN 주소(fbcdn.net / cdninstagram.com)만 허용됩니다.")
    return parsed._replace(fragment="").geturl()


def sniff_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) > 16 and data[4:8] == b"ftyp":
        brand = data[8:32]
        if b"avif" in brand or b"avis" in brand:
            return ".avif"
        if any(b in brand for b in (b"heic", b"heix", b"hevc", b"mif1")):
            return ".heic"
    return None


def fetch_image(url: str) -> tuple[bytes | None, str | None, str]:
    try:
        with requests.get(
            url, stream=True, allow_redirects=False, timeout=(7, 22),
            headers={"Accept": "image/avif,image/webp,image/*;q=0.8"}
        ) as response:
            if response.status_code in (401, 403, 404, 410):
                return None, None, "URL이 만료되었거나 이미지 CDN 접근이 거부되었습니다."
            if response.status_code != 200:
                return None, None, f"CDN 요청 오류(HTTP {response.status_code})"
            if int(response.headers.get("Content-Length", "0") or 0) > MAX_IMAGE_BYTES:
                return None, None, "이미지가 18MB 제한을 초과했습니다."
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    return None, None, "이미지가 18MB 제한을 초과했습니다."
                chunks.append(chunk)
            data = b"".join(chunks)
            ext = sniff_extension(data)
            if ext is None:
                return None, None, "이미지 파일이 아닙니다. Network → Img에서 사진의 URL을 복사해 주세요."
            return data, ext, ""
    except (requests.RequestException, ValueError):
        return None, None, "CDN에 연결하지 못했습니다. 사진 URL을 새로 복사해 주세요."


def register_manual_routes(app, access_key: str, rate_limited, jobs):
    @app.route("/api/download-direct", methods=["POST", "OPTIONS"])
    def download_direct():
        if request.method == "OPTIONS":
            return ("", 204)
        if access_key and request.headers.get("X-App-Key") != access_key:
            return jsonify(error="서버 접근 키가 필요하거나 올바르지 않습니다."), 401
        data = request.get_json(silent=True)
        images = data.get("image_urls") if isinstance(data, dict) else None
        if not isinstance(images, list) or not 1 <= len(images) <= 15:
            return jsonify(error="이미지 URL을 1~15개 입력해 주세요."), 400
        try:
            urls = list(dict.fromkeys(validate_url(item) for item in images))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if rate_limited(request.remote_addr or "unknown"):
            return jsonify(error="요청이 많습니다. 15분 뒤 다시 시도해 주세요."), 429
        if not jobs.acquire(blocking=False):
            return jsonify(error="다른 다운로드가 진행 중입니다."), 503
        try:
            out = io.BytesIO()
            failures, count, used_bytes = [], 0, 0
            with ZipFile(out, "w", compression=ZIP_STORED, allowZip64=False) as zf:
                # Keep memory bounded and avoid 15 serial CDN timeouts.
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(fetch_image, url): i for i, url in enumerate(urls, start=1)}
                    for future in as_completed(futures):
                        i = futures[future]
                        try:
                            content, ext, err = future.result()
                        except Exception:
                            content, ext, err = None, None, "이미지 처리 중 오류가 발생했습니다."
                        if content is None or ext is None:
                            failures.append(f"{i}번째 이미지: {err}")
                            continue
                        if used_bytes + len(content) > MAX_ZIP_BYTES:
                            return jsonify(error="사진 총용량이 80MB 제한을 초과했습니다."), 413
                        used_bytes += len(content)
                        count += 1
                        zf.writestr(f"image_{i:02d}{ext}", content)
                if failures:
                    zf.writestr("download_report.txt", "\n".join(sorted(failures)).encode("utf-8"))
            if not count:
                return jsonify(error=failures[0].split(": ", 1)[-1] if failures else "사진이 없습니다."), 422
            out.seek(0)
            filename = f"instagram_network_photos_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.zip"
            result = send_file(out, mimetype="application/zip", as_attachment=True, download_name=filename)
            result.headers["X-Photo-Count"] = str(count)
            result.headers["X-Failed-Posts"] = str(len(failures))
            result.headers["Cache-Control"] = "no-store"
            return result
        finally:
            jobs.release()
