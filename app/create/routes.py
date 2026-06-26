"""Create blueprint: /create, /result/<id>, /files/<id>/<kind> — §12."""
import json
import os
import re
from urllib.parse import urlparse

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request,
    send_file, url_for,
)
from flask_login import current_user, login_required

from .. import db
from ..models import BitlyDomain, CardTemplate, Logo, QRCode, get_setting, get_setting_bool
from ..services import bitly, card_composer, packaging, qr_local, qr_monkey
from ..utils import role_required


def _get_qr_method_and_style():
    """Return (method_str, style_dict) from the current admin QR design settings."""
    method = get_setting("qr_method") or "qrcode_monkey"
    raw = get_setting("qr_style_json")
    try:
        style = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        style = {}
    return method, style

bp = Blueprint("create", __name__)

MODES = ("shortlink_only", "qr_only", "full_card")
BACKHALF_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _form_context():
    return {
        "logos": Logo.query.filter_by(is_active=True).order_by(Logo.name).all(),
        "domains": BitlyDomain.query.filter_by(is_active=True)
        .order_by(BitlyDomain.domain)
        .all(),
        "templates": CardTemplate.query.filter_by(is_active=True)
        .order_by(CardTemplate.name)
        .all(),
        "allow_default_domain": get_setting_bool("allow_bitly_default_domain"),
    }


def _valid_url(value):
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


@bp.route("/create", methods=["GET", "POST"])
@login_required
@role_required("user")
def create():
    ctx = _form_context()
    if request.method != "POST":
        preselect = request.args.get("mode")
        if preselect not in MODES:
            preselect = "full_card"
        return render_template("create/form.html", preselect=preselect, **ctx)

    form = request.form
    mode = form.get("mode", "")
    title = form.get("title", "").strip()
    long_url = form.get("long_url", "").strip()
    skip_bitly_fallback = form.get("skip_bitly_fallback") == "1"
    qr_method, qr_style = _get_qr_method_and_style()

    # ── validation ──────────────────────────────────────────────────────
    errors = []
    if mode not in MODES:
        errors.append("Choose a generation mode.")
    if not title:
        errors.append("A title is required.")
    if not _valid_url(long_url):
        errors.append("Enter a valid destination URL (must start with http:// or https://).")

    domain = None
    domain_row = None
    if mode in ("shortlink_only", "full_card"):
        domain_id = form.get("bitly_domain_id", "")
        if domain_id == "default":
            if not ctx["allow_default_domain"]:
                errors.append("The default bit.ly domain is not allowed; choose a branded domain.")
        elif domain_id:
            domain_row = db.session.get(BitlyDomain, int(domain_id))
            if domain_row is None or not domain_row.is_active:
                errors.append("Choose a valid Bitly domain.")
            else:
                domain = domain_row.domain
        else:
            errors.append("Choose a Bitly domain.")

    custom_backhalf = form.get("custom_backhalf", "").strip() or None
    if custom_backhalf:
        if not current_user.can_custom_backhalves:
            custom_backhalf = None  # silently ignore — field shouldn't render
        elif not BACKHALF_RE.match(custom_backhalf):
            errors.append("Custom back-half may only contain letters, numbers, hyphens, and underscores.")

    logo = template = None
    cta_text = None
    if mode in ("qr_only", "full_card"):
        # Both modes need a template for the card frame
        template_id = form.get("card_template_id", "")
        template = db.session.get(CardTemplate, int(template_id)) if template_id else None
        if template is None or not template.is_active:
            # Fall back to the system default rather than hard-erroring
            template = CardTemplate.query.filter_by(is_default=True, is_active=True).first() \
                or CardTemplate.query.filter_by(is_active=True).first()
        if template is None:
            errors.append("No card template is configured. Ask an administrator to add one.")
        # Logo is optional for both modes; logo for full_card is required
        logo_id = form.get("logo_id", "")
        logo = db.session.get(Logo, int(logo_id)) if logo_id else None
        if logo is not None and not logo.is_active:
            logo = None
        if mode == "full_card" and logo is None and qr_method != "local":
            errors.append("Choose a logo for the QR code.")
        # Both qr_only and full_card produce a framed text card, so both get a
        # CTA line. Default from the template; user may opt in to edit it.
        if template is not None:
            cta_text = template.default_cta_text
            if form.get("edit_cta") == "1":  # §12.1 opt-in checkbox
                custom_cta = form.get("cta_text", "").strip()
                if custom_cta:
                    cta_text = custom_cta

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("create/form.html", form=form, **ctx), 400

    # ── short link (Bitly) ──────────────────────────────────────────────
    short_url = bitly_id = None
    if mode in ("shortlink_only", "full_card") and not skip_bitly_fallback:
        try:
            result = bitly.shorten(
                long_url, domain=domain, custom_backhalf=custom_backhalf
            )
            short_url, bitly_id = result["link"], result["id"]
        except bitly.BitlyError as exc:
            flash(f"Bitly error: {exc}", "danger")
            if mode == "full_card":
                # §8.1: offer to proceed with the original URL in the QR code
                flash(
                    "You can proceed without a short link — the QR code will "
                    "contain the original URL instead.",
                    "warning",
                )
                return render_template(
                    "create/form.html", form=form, offer_fallback=True, **ctx
                ), 502
            return render_template("create/form.html", form=form, **ctx), 502

    record = QRCode(
        user_id=current_user.id,
        generation_mode=mode,
        title=title,
        long_url=long_url,
        short_url=short_url,
        bitly_id=bitly_id,
        bitly_domain_id=domain_row.id if domain_row else None,
        custom_backhalf=custom_backhalf,
        cta_text=cta_text if mode in ("qr_only", "full_card") else None,
        card_template_id=template.id if template else None,
        logo_id=logo.id if logo else None,
    )
    db.session.add(record)
    db.session.commit()

    if mode == "shortlink_only":
        return redirect(url_for("create.result", qr_id=record.id))

    # ── QR generation (qr_only / full_card) ──────────────────────────────
    qr_data = short_url or long_url
    url_text = short_url or long_url
    out_dir = os.path.join(current_app.config["OUTPUT_FOLDER"], f"qr_{record.id}")
    os.makedirs(out_dir, exist_ok=True)
    try:
        if qr_method == "local":
            # Local mode: logos not supported — warn if one was selected.
            if logo is not None:
                flash(
                    "Logo embedding is not available in local QR generation mode; "
                    "the QR code will be generated without a logo.",
                    "warning",
                )

            def _fetch():
                svg_b, cfg = qr_local.generate(
                    qr_data, "svg", qr_monkey.SVG_SIZE, style=qr_style
                )
                png_b, _ = qr_local.generate(
                    qr_data, "png", qr_monkey.PNG_SIZE, style=qr_style
                )
                return svg_b, png_b, cfg

            qr_svg_bytes, qr_png_bytes, config = _fetch()
        else:
            # QRCode Monkey path: upload logo once for a token, reuse on retries.
            logo_path = None
            token = None
            if logo is not None:
                logo_path = os.path.join(
                    current_app.config["UPLOAD_FOLDER"], logo.filename
                )
                token = qr_monkey.get_logo_token(logo, logo_path)

            def _fetch():
                svg_b, cfg = qr_monkey.generate(
                    qr_data, "svg", qr_monkey.SVG_SIZE,
                    logo_token=token, style=qr_style
                )
                png_b, _ = qr_monkey.generate(
                    qr_data, "png", qr_monkey.PNG_SIZE,
                    logo_token=token, style=qr_style
                )
                return svg_b, png_b, cfg

            try:
                qr_svg_bytes, qr_png_bytes, config = _fetch()
            except qr_monkey.QRMonkeyError:
                if logo is not None:
                    token = qr_monkey.refresh_logo_token(logo, logo_path)
                    qr_svg_bytes, qr_png_bytes, config = _fetch()
                else:
                    raise

        record.qr_config_json = qr_monkey.config_snapshot(
            config, qr_data, qr_monkey.PNG_SIZE
        )

        qr_svg_str = qr_svg_bytes.decode("utf-8")
        qr_png_path = os.path.join(out_dir, "qr_raw.png")
        qr_svg_path = os.path.join(out_dir, "qr_raw.svg")
        with open(qr_png_path, "wb") as fh:
            fh.write(qr_png_bytes)
        with open(qr_svg_path, "w", encoding="utf-8") as fh:
            fh.write(qr_svg_str)
        record.qr_png_path = qr_png_path
        record.qr_svg_path = qr_svg_path

        # Full framed card (both qr_only and full_card).
        fonts_dir = os.path.join(current_app.static_folder, "fonts")
        svg_str, png_bytes = card_composer.compose(
            qr_svg_str, template, cta_text, url_text, fonts_dir
        )
        png_path = os.path.join(out_dir, "card_print.png")
        svg_path = os.path.join(out_dir, "card_print.svg")
        with open(png_path, "wb") as fh:
            fh.write(png_bytes)
        with open(svg_path, "w", encoding="utf-8") as fh:
            fh.write(svg_str)
        record.png_path = png_path
        record.svg_path = svg_path

        zip_files = {
            "card_print.png": png_path,
            "card_print.svg": svg_path,
            "qr_raw.png": qr_png_path,
            "qr_raw.svg": qr_svg_path,
        }
        record.zip_path = packaging.build_zip(out_dir, zip_files)
        db.session.commit()
    except (
        qr_monkey.QRMonkeyError,
        qr_local.QRLocalError,
        card_composer.ComposeError,
        OSError,
    ) as exc:
        db.session.delete(record)
        db.session.commit()
        flash(f"Generation failed: {exc}", "danger")
        return render_template("create/form.html", form=form, **ctx), 502

    return redirect(url_for("create.result", qr_id=record.id))


@bp.route("/result/<int:qr_id>")
@login_required
def result(qr_id):
    record = db.session.get(QRCode, qr_id) or abort(404)
    if record.user_id != current_user.id and not current_user.role_at_least("reporter"):
        abort(403)
    return render_template("create/result.html", r=record)


FILE_KINDS = {
    "zip": ("zip_path", "package.zip"),
    "png": ("png_path", "card_print.png"),
    "svg": ("svg_path", "card_print.svg"),
    "qr_png": ("qr_png_path", "qr_raw.png"),
    "qr_svg": ("qr_svg_path", "qr_raw.svg"),
}


@bp.route("/files/<int:qr_id>/<kind>")
@login_required
def files(qr_id, kind):
    """§14.1: generated files are served through authenticated routes only."""
    if kind not in FILE_KINDS:
        abort(404)
    record = db.session.get(QRCode, qr_id) or abort(404)
    if record.user_id != current_user.id and not current_user.role_at_least("reporter"):
        abort(403)
    attr, download_name = FILE_KINDS[kind]
    path = getattr(record, attr)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=f"{record.id}_{download_name}")
