"""Gyazo screenshot upload utility."""
import os
import io
import json
import logging
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GYAZO_UPLOAD_URL = "https://upload.gyazo.com/api/upload"
GYAZO_ACCESS_TOKEN = os.environ.get("GYAZO_ACCESS_TOKEN", "")


def upload_screenshot(page, title: str = "") -> str | None:
    """Take a screenshot and upload to Gyazo. Returns the Gyazo URL or None."""
    if not GYAZO_ACCESS_TOKEN:
        logger.warning("Gyazo: no access token")
        return None
    try:
        png_bytes = page.screenshot(type="png", full_page=False)
        boundary = "----GyazoBoundary"
        body = io.BytesIO()

        def write_field(name, value):
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.write(f"{value}\r\n".encode())

        def write_file(name, filename, data, content_type="image/png"):
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
            body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.write(data)
            body.write(b"\r\n")

        write_field("access_token", GYAZO_ACCESS_TOKEN)
        if title:
            write_field("title", title)
            write_field("desc", title)
        write_file("imagedata", "screenshot.png", png_bytes)
        body.write(f"--{boundary}--\r\n".encode())

        req = Request(
            GYAZO_UPLOAD_URL,
            data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            url = result.get("permalink_url") or result.get("url", "")
            logger.info(f"Gyazo upload OK: {url}")
            return url
    except Exception as e:
        logger.warning(f"Gyazo upload failed: {type(e).__name__}: {e}")
        return None
