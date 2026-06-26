"""Local QR code generation using segno — admin-selected alternative to QRCode Monkey.

segno supports body/background color and error correction level only.
Shape, per-eye color, gradient, logo embedding, and eye rotation features
require QRCode Monkey and are disabled in the UI when this method is active.
"""
import io

_BORDER = 4  # quiet-zone width in modules


class QRLocalError(Exception):
    pass


def generate(data_url, file_format, size, style=None, logo_token=None):
    """Generate a styled QR code using segno.

    Returns ``(content_bytes, config_dict)``. ``logo_token`` is accepted for
    API symmetry with qr_monkey.generate but is ignored — logo embedding is
    not supported locally. ``size`` is the target output dimension in pixels;
    scale is derived automatically.
    """
    try:
        import segno
    except ImportError as exc:
        raise QRLocalError(
            "segno is not installed. Rebuild the Docker image after adding "
            "'segno>=1.6' to requirements.txt."
        ) from exc

    s = style or {}
    ec = s.get("ecLevel", "H" if logo_token else "M")
    dark = s.get("bodyColor", "#1E395E")
    light = s.get("bgColor", "#FFFFFF")

    try:
        qr = segno.make_qr(data_url, error=ec)
    except Exception as exc:
        raise QRLocalError(f"QR generation failed: {exc}") from exc

    # Scale so that (modules + 2×border) × scale ≈ size pixels.
    modules = qr.symbol_size()[0]
    total_modules = modules + 2 * _BORDER
    scale = max(1, round(size / total_modules))

    buf = io.BytesIO()
    try:
        if file_format == "svg":
            qr.save(buf, kind="svg", scale=scale, dark=dark, light=light,
                    border=_BORDER)
        else:
            qr.save(buf, kind="png", scale=scale, dark=dark, light=light,
                    border=_BORDER)
    except Exception as exc:
        raise QRLocalError(f"QR save failed: {exc}") from exc

    buf.seek(0)
    content = buf.read()

    if file_format == "svg" and not content.lstrip().startswith((b"<?xml", b"<svg")):
        raise QRLocalError("segno did not return SVG content")
    if file_format == "png" and not content.startswith(b"\x89PNG"):
        raise QRLocalError("segno did not return PNG content")

    used_config = {"ecLevel": ec, "bodyColor": dark, "bgColor": light, "method": "local"}
    return content, used_config
