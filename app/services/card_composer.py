"""Card composition — DESIGN.md §9.

The card is assembled as an SVG string (1275 x 1650 user units) and
converted to a 300 dpi PNG via CairoSVG. Geometry is driven by the card
template: outer and inner corner radius, QR size, and the vertical position
of the CTA and URL text lines are all template-configurable (§9.2/§9.3).

The QR is embedded as a nested vector SVG (the API's SVG output, logo
already included) so it scales cleanly in both the SVG deliverable and the
PNG render. Text lines are auto-sized so each fills the inner panel width.
"""
import os
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from PIL import ImageFont

CARD_W, CARD_H = 1275, 1650

# Layout zones (§9.2)
FRAME_W = 90                            # outer frame thickness
PANEL_X = FRAME_W
PANEL_Y = FRAME_W
PANEL_W = CARD_W - 2 * FRAME_W          # 1095
PANEL_H = 1050                          # white QR panel height
# Both text lines auto-size to exactly this width so the CTA and the URL are
# always the same width as each other (the inner frame width less a small
# margin). No upper cap — short text simply grows to fill the width.
TEXT_TARGET_W = PANEL_W - 80            # auto-size target width (1015)

# Default sizing fallbacks (used when a template predates the sizing columns).
DEFAULT_QR_SIZE = 980
DEFAULT_CTA_Y = 1320
DEFAULT_URL_Y = 1480

# §9.4 font weights: CTA = Inter SemiBold (600), URL = Inter Light (300).
CTA_WEIGHT = "600"
URL_WEIGHT = "300"


class ComposeError(Exception):
    pass


def _font_path(fonts_dir, weight):
    name = {"600": "Inter-SemiBold.ttf", "300": "Inter-Light.ttf"}[weight]
    path = os.path.join(fonts_dir, name)
    if not os.path.exists(path):
        raise ComposeError(
            f"Font file missing: {path}. The Docker image downloads Inter at "
            "build time; for bare installs place the TTFs in app/static/fonts/."
        )
    return path


def _fit_font_size(text, font_file):
    """Font size (px) so `text` renders exactly TEXT_TARGET_W wide."""
    probe = ImageFont.truetype(font_file, 100)
    width = probe.getlength(text) or 1.0
    return max(12, int(100 * TEXT_TARGET_W / width))


def _nest_qr_svg(qr_svg_string, qr_size):
    """Embed the finished QR SVG as a nested vector element, centred
    horizontally in the card and vertically within the white panel."""
    try:
        qr_root = ET.fromstring(qr_svg_string)
    except ET.ParseError as exc:
        raise ComposeError(f"QR SVG did not parse for embedding: {exc}") from exc
    qr_root.set("x", f"{(CARD_W - qr_size) / 2:.0f}")
    qr_root.set("y", f"{PANEL_Y + (PANEL_H - qr_size) / 2:.0f}")
    qr_root.set("width", str(qr_size))
    qr_root.set("height", str(qr_size))
    return ET.tostring(qr_root, encoding="unicode")


def compose_svg(qr_svg_string, template, cta_text, url_text, fonts_dir):
    """Build the framed card as an SVG string."""
    radius = template.effective_radius
    panel_radius = getattr(template, "effective_inner_radius", max(radius - FRAME_W, 0))
    qr_size = getattr(template, "qr_size_px", None) or DEFAULT_QR_SIZE
    cta_y = getattr(template, "cta_baseline_y", None) or DEFAULT_CTA_Y
    url_y = getattr(template, "url_baseline_y", None) or DEFAULT_URL_Y

    qr_fragment = _nest_qr_svg(qr_svg_string, qr_size)

    cta_size = _fit_font_size(cta_text, _font_path(fonts_dir, CTA_WEIGHT))
    url_size = _fit_font_size(url_text, _font_path(fonts_dir, URL_WEIGHT))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{CARD_W}" height="{CARD_H}" viewBox="0 0 {CARD_W} {CARD_H}">
  <rect x="0" y="0" width="{CARD_W}" height="{CARD_H}" rx="{radius}" ry="{radius}" fill="{template.background_color}"/>
  <rect x="{PANEL_X}" y="{PANEL_Y}" width="{PANEL_W}" height="{PANEL_H}" rx="{panel_radius}" ry="{panel_radius}" fill="{template.panel_color}"/>
  {qr_fragment}
  <text x="{CARD_W / 2:.0f}" y="{cta_y}" font-family="Inter" font-weight="{CTA_WEIGHT}" font-size="{cta_size}" fill="{template.text_color}" text-anchor="middle">{escape(cta_text)}</text>
  <text x="{CARD_W / 2:.0f}" y="{url_y}" font-family="Inter" font-weight="{URL_WEIGHT}" font-size="{url_size}" fill="{template.text_color}" text-anchor="middle">{escape(url_text)}</text>
</svg>
"""


def svg_to_png(svg_string):
    """Convert the card SVG to a 300 dpi PNG (1275 x 1650 px)."""
    import cairosvg  # deferred: needs libcairo2 (present in the Docker image)

    return cairosvg.svg2png(
        bytestring=svg_string.encode("utf-8"),
        output_width=CARD_W,
        output_height=CARD_H,
    )


def compose(qr_svg_string, template, cta_text, url_text, fonts_dir):
    """Returns (svg_string, png_bytes) for the framed card."""
    svg = compose_svg(qr_svg_string, template, cta_text, url_text, fonts_dir)
    return svg, svg_to_png(svg)
