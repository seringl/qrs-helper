"""QRCode Monkey API client — DESIGN.md §8.2/§8.3.

The logo is embedded by QRCode Monkey itself (not composited locally): the
selected logo file is uploaded once to ``/qr/uploadImage`` to obtain a
filename token, which is then passed to ``/qr/custom``. The token is cached
on the Logo row and **reused** on later generations so the same image is not
re-uploaded every time. If a cached token has gone stale the API call fails
and the caller refreshes it (see ``create/routes.py``).

The QR is delivered exactly as the API returns it — both a high-resolution
PNG and a vector SVG. No local post-processing is applied; the approved
style (circular body, frame2/ball2 eyes, navy colour, mirrored upper-left
eye) is requested directly in QR_STYLE below.
"""
import json
import os
from datetime import datetime, timezone

import requests

from .. import db

TIMEOUT = 30

# Reuse a cached upload token for this long before forcing a fresh upload.
# (The caller also re-uploads automatically if the API rejects a stale token.)
TOKEN_TTL_SECONDS = 6 * 3600

# Standalone PNG size requested from the API (highest practical resolution
# on the free endpoint). The SVG is vector, so it is resolution-independent.
PNG_SIZE = 2000
SVG_SIZE = 1275

# §8.3 approved standard QR style. Eye/eyeball colours are requested
# explicitly because the API otherwise renders eyes black. The upper-left
# eye frame and ball are flipped horizontally via erf1/erf1b so frame2/ball2
# face the correct direction.
QR_STYLE = {
    "body": "circle",
    "eye": "frame2",
    "eyeBall": "ball2",
    "bodyColor": "#1E395E",
    "bgColor": "#FFFFFF",
    "eye1Color": "#1E395E",
    "eye2Color": "#1E395E",
    "eye3Color": "#1E395E",
    "eyeBall1Color": "#1E395E",
    "eyeBall2Color": "#1E395E",
    "eyeBall3Color": "#1E395E",
    "erf1": ["fh"],
    "erf1b": ["fh"],
}

BODY_COLOR = QR_STYLE["bodyColor"]


class QRMonkeyError(Exception):
    pass


def _base():
    return os.environ.get("QRMONKEY_BASE_URL", "https://api.qrcode-monkey.com").rstrip("/")


# ── Logo upload + token cache ──────────────────────────────────────────────
def _extract_token(response):
    """Pull the image filename/id out of an /qr/uploadImage response.

    The endpoint may return the id as plain text, as a JSON string
    ("abc123.png"), or wrapped in a JSON object ({"file": "abc123.png"}).
    Passing the whole JSON blob as the logo id makes /qr/custom reply
    `errorCode 5 "Image is not existing"`, so we normalise all shapes here.
    """
    raw = (response.text or "").strip()
    try:
        data = response.json()
    except ValueError:
        return raw.strip('"').strip()
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        for key in ("file", "filename", "name", "image", "id"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for val in data.values():  # fall back to the first string value
            if isinstance(val, str) and val.strip():
                return val.strip()
    return raw.strip('"').strip()


def upload_logo(logo_path):
    """Upload a logo file to QRCode Monkey. Returns the filename/id token."""
    with open(logo_path, "rb") as fh:
        files = {"file": (os.path.basename(logo_path), fh)}
        r = requests.post(f"{_base()}/qr/uploadImage", files=files, timeout=TIMEOUT)
    if r.status_code != 200:
        raise QRMonkeyError(
            f"Logo upload failed ({r.status_code}): {r.text[:300]}"
        )
    token = _extract_token(r)
    if not token:
        raise QRMonkeyError(
            f"Logo upload returned no usable token: {r.text[:200]!r}"
        )
    return token


def _store_token(logo, token):
    logo.qrm_token = token
    logo.qrm_token_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()


def _token_is_fresh(logo):
    if not logo.qrm_token or not logo.qrm_token_at:
        return False
    age = datetime.now(timezone.utc).replace(tzinfo=None) - logo.qrm_token_at
    return age.total_seconds() < TOKEN_TTL_SECONDS


def get_logo_token(logo, logo_path):
    """Return a usable upload token, reusing the cached one when still fresh."""
    if _token_is_fresh(logo):
        return logo.qrm_token
    token = upload_logo(logo_path)
    _store_token(logo, token)
    return token


def refresh_logo_token(logo, logo_path):
    """Force a fresh upload (used when a cached token is rejected)."""
    token = upload_logo(logo_path)
    _store_token(logo, token)
    return token


# ── QR generation ──────────────────────────────────────────────────────────
def generate(data_url, file_format, size, logo_token=None):
    """Fetch the styled QR in ``file_format`` ("png" or "svg").

    Returns (content_bytes, config). Error correction is H when a logo is
    embedded (so the logo cannot eat into recoverable data), otherwise M.
    """
    config = dict(QR_STYLE)
    config["ecLevel"] = "H" if logo_token else "M"
    if logo_token:
        config["logo"] = logo_token
        # "clean" knocks QR modules out behind the logo for a crisp edge.
        config["logoMode"] = "clean"
    payload = {
        "data": data_url,
        "config": config,
        "size": size,
        "download": False,
        "file": file_format,
    }
    r = requests.post(f"{_base()}/qr/custom", json=payload, timeout=TIMEOUT)
    if r.status_code != 200:
        raise QRMonkeyError(
            f"QR generation failed ({r.status_code}): {r.text[:300]}"
        )
    body = r.content
    if file_format == "svg" and not body.lstrip().startswith((b"<?xml", b"<svg")):
        raise QRMonkeyError("QR API did not return SVG content")
    if file_format == "png" and not body.startswith(b"\x89PNG"):
        raise QRMonkeyError("QR API did not return PNG content")
    return body, config


def config_snapshot(config, data_url, size):
    return json.dumps({"data": data_url, "size": size, "config": config})
