"""Admin blueprint: users, logos, card templates, domains, settings — §11."""
import json
import os
import re
import uuid

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect, render_template,
    request, url_for,
)
from flask_login import current_user, login_required

from .. import bcrypt, db
from ..models import (
    ROLES, BitlyDomain, CardTemplate, Logo, QRCode, User,
    SETTING_DEFAULTS, SETTING_DESCRIPTIONS, get_setting, set_setting,
)
from ..services.analytics_harvester import cleanup_retention, harvest_all
from ..services.qr_monkey import DEFAULT_QR_STYLE
from ..services.setup_service import _dinopass_password
from ..utils import role_required

# ── QR design constants ──────────────────────────────────────────────────────

BODY_SHAPES = [
    ("square", "Square"), ("mosaic", "Mosaic"), ("dot", "Dot"),
    ("circle", "Circle (ring)"), ("circle-zebra", "Circle zebra"),
    ("circle-zebra-vertical", "Circle zebra vertical"),
    ("circular", "Circular"), ("edge-cut", "Edge cut"),
    ("edge-cut-smooth", "Edge cut smooth"), ("japanesse", "Japanese"),
    ("japanesse-circular", "Japanese circular"), ("sharp", "Sharp"),
    ("sharp-smooth", "Sharp smooth"), ("diamond", "Diamond"),
    ("diamond-small", "Diamond small"), ("star", "Star"), ("heart", "Heart"),
    ("pointed", "Pointed"), ("pointed-in", "Pointed in"),
    ("pointed-out", "Pointed out"), ("pointed-edge-cut", "Pointed edge cut"),
    ("wave", "Wave"), ("spike", "Spike"),
]

EYE_FRAMES = [
    ("frame0", "0 — plain square"), ("frame1", "1"), ("frame2", "2 — corner tab"),
    ("frame3", "3 — rounded"), ("frame4", "4 — circle"), ("frame5", "5 — leaf"),
    ("frame6", "6"), ("frame7", "7 — arrow"), ("frame8", "8 — diamond"),
    ("frame10", "10"), ("frame11", "11"), ("frame12", "12"),
    ("frame13", "13"), ("frame14", "14"), ("frame16", "16"),
]

EYE_BALLS = [
    ("ball0", "0 — plain square"), ("ball1", "1"), ("ball2", "2 — corner tab"),
    ("ball3", "3 — rounded"), ("ball4", "4 — circle"), ("ball5", "5 — leaf"),
    ("ball6", "6"), ("ball7", "7"), ("ball8", "8 — diamond"),
    ("ball10", "10"), ("ball11", "11"), ("ball12", "12"),
    ("ball13", "13"), ("ball14", "14"), ("ball15", "15"),
]

EYE_TRANSFORMS = [
    ("fh", "Flip horizontal"), ("fv", "Flip vertical"),
    ("r90", "Rotate 90°"), ("r180", "Rotate 180°"), ("r270", "Rotate 270°"),
]

_EYE_KEYS = [
    # erf = eye frame rotation, brf = eye ball rotation — qrcode-monkey.com/qr-code-api-with-logo/
    ("erf1", "Upper-left frame"), ("brf1", "Upper-left ball"),
    ("erf2", "Upper-right frame"), ("brf2", "Upper-right ball"),
    ("erf3", "Lower-left frame"), ("brf3", "Lower-left ball"),
]


def _parse_form_to_style(form):
    """Build a qr_style dict from a form submission."""
    def transforms(prefix):
        return [t for t, _ in EYE_TRANSFORMS if form.get(f"{prefix}_{t}") == "on"]

    return {
        "body": form.get("body", DEFAULT_QR_STYLE["body"]),
        "eye": form.get("eye", DEFAULT_QR_STYLE["eye"]),
        "eyeBall": form.get("eyeBall", DEFAULT_QR_STYLE["eyeBall"]),
        "bodyColor": form.get("bodyColor", DEFAULT_QR_STYLE["bodyColor"]),
        "bgColor": form.get("bgColor", DEFAULT_QR_STYLE["bgColor"]),
        "eyeColor": form.get("eyeColor", DEFAULT_QR_STYLE["eyeColor"]),
        "eyeBallColor": form.get("eyeBallColor", DEFAULT_QR_STYLE["eyeBallColor"]),
        "erf1": transforms("erf1"),
        "erf2": transforms("erf2"),
        "erf3": transforms("erf3"),
        "brf1": transforms("brf1"),
        "brf2": transforms("brf2"),
        "brf3": transforms("brf3"),
        "ecLevel": form.get("ecLevel", DEFAULT_QR_STYLE["ecLevel"]),
        "gradientEnabled": form.get("gradientEnabled") == "on",
        "gradientColor1": form.get("gradientColor1", DEFAULT_QR_STYLE["gradientColor1"]),
        "gradientColor2": form.get("gradientColor2", DEFAULT_QR_STYLE["gradientColor2"]),
        "gradientType": form.get("gradientType", DEFAULT_QR_STYLE["gradientType"]),
        "gradientOnEyes": form.get("gradientOnEyes") == "on",
    }


def _load_qr_style():
    """Return the current qr_style dict from app settings, falling back to defaults."""
    raw = get_setting("qr_style_json")
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return dict(DEFAULT_QR_STYLE)

bp = Blueprint("admin", __name__)

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ALLOWED_LOGO_EXT = {".png", ".jpg", ".jpeg", ".svg"}


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return redirect(url_for("admin.users"))


# ── Users ────────────────────────────────────────────────────────────────
@bp.route("/users")
@login_required
@role_required("admin")
def users():
    rows = User.query.order_by(User.username).all()
    return render_template("admin/users.html", users=rows, roles=ROLES)


@bp.route("/users/new", methods=["POST"])
@login_required
@role_required("admin")
def create_user():
    """v2.4: admins create local users with a temp password (force-reset)."""
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    email = request.form.get("email", "").strip() or None
    role = request.form.get("role", "user")
    if role not in ROLES:
        role = "user"
    if not username or not display_name:
        flash("Username and display name are required.", "danger")
    elif User.query.filter_by(username=username).first():
        flash("That username is already taken.", "danger")
    else:
        password = _dinopass_password()
        db.session.add(
            User(
                username=username,
                display_name=display_name,
                email=email,
                auth_type="local",
                role=role,
                password_hash=bcrypt.generate_password_hash(password).decode(),
                force_password_reset=True,
                can_custom_backhalves=request.form.get("can_custom_backhalves") == "on",
            )
        )
        db.session.commit()
        flash(
            f"User {username} created with role '{role}'. Temporary password: "
            f"{password} (they must change it on first login)",
            "success",
        )
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    role = request.form.get("role")
    if role in ROLES:
        if user.id == current_user.id and role != "admin":
            flash("You cannot demote your own account.", "danger")
            return redirect(url_for("admin.users"))
        user.role = role
    user.can_custom_backhalves = request.form.get("can_custom_backhalves") == "on"
    if user.id != current_user.id:
        user.is_active = request.form.get("is_active") == "on"
    expiry = request.form.get("session_expiry_days", "").strip()
    user.session_expiry_days = int(expiry) if expiry.isdigit() else None
    db.session.commit()
    flash(f"Updated {user.username}.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@role_required("admin")
def reset_user_password(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.auth_type != "local":
        flash("Directory accounts manage passwords in the directory.", "warning")
        return redirect(url_for("admin.users"))
    password = _dinopass_password()
    user.password_hash = bcrypt.generate_password_hash(password).decode()
    user.force_password_reset = True
    db.session.commit()
    flash(
        f"Temporary password for {user.username}: {password} "
        "(they must change it on next login)",
        "success",
    )
    return redirect(url_for("admin.users"))


# ── Logos (§ logo library is admin-managed) ─────────────────────────────
@bp.route("/logos", methods=["GET", "POST"])
@login_required
@role_required("admin")
def logos():
    if request.method == "POST":
        file = request.files.get("file")
        name = request.form.get("name", "").strip()
        if not file or not file.filename or not name:
            flash("A display name and an image file are required.", "danger")
        else:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ALLOWED_LOGO_EXT:
                flash("Allowed formats: PNG, JPG, SVG.", "danger")
            elif not _content_ok(file, ext):
                flash("The file content does not match its extension.", "danger")
            else:
                filename = f"{uuid.uuid4().hex}{ext}"  # §14.1 UUID rename
                os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
                file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                db.session.add(
                    Logo(name=name, filename=filename, uploaded_by=current_user.id)
                )
                db.session.commit()
                flash(f"Logo '{name}' uploaded.", "success")
        return redirect(url_for("admin.logos"))
    rows = Logo.query.order_by(Logo.name).all()
    return render_template("admin/logos.html", logos=rows)


def _content_ok(file, ext):
    """§14.1: validate content, not just the extension."""
    head = file.stream.read(512)
    file.stream.seek(0)
    if ext == ".png":
        return head.startswith(b"\x89PNG")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8")
    if ext == ".svg":
        sniff = head.lstrip()[:200].lower()
        return sniff.startswith(b"<?xml") or sniff.startswith(b"<svg")
    return False


@bp.route("/logos/<int:logo_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_logo(logo_id):
    logo = db.session.get(Logo, logo_id) or abort(404)
    action = request.form.get("action")
    if action == "toggle":
        logo.is_active = not logo.is_active
    elif action == "default":
        Logo.query.update({Logo.is_global_default: False})
        logo.is_global_default = True
    db.session.commit()
    return redirect(url_for("admin.logos"))


# ── Card templates ───────────────────────────────────────────────────────
@bp.route("/templates", methods=["GET", "POST"])
@login_required
@role_required("admin")
def templates():
    if request.method == "POST":
        tpl, errors = _template_from_form(CardTemplate(created_by=current_user.id))
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            db.session.add(tpl)
            if tpl.is_default:
                CardTemplate.query.filter(CardTemplate.id != tpl.id).update(
                    {CardTemplate.is_default: False}
                )
            db.session.commit()
            flash(f"Template '{tpl.name}' created.", "success")
        return redirect(url_for("admin.templates"))
    rows = CardTemplate.query.order_by(CardTemplate.name).all()
    return render_template("admin/templates.html", templates=rows, edit=None)


@bp.route("/templates/<int:tpl_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit_template(tpl_id):
    tpl = db.session.get(CardTemplate, tpl_id) or abort(404)
    if request.method == "POST":
        _, errors = _template_from_form(tpl)
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            if tpl.is_default:
                CardTemplate.query.filter(CardTemplate.id != tpl.id).update(
                    {CardTemplate.is_default: False}
                )
            db.session.commit()
            flash(f"Template '{tpl.name}' updated.", "success")
            return redirect(url_for("admin.templates"))
    rows = CardTemplate.query.order_by(CardTemplate.name).all()
    return render_template("admin/templates.html", templates=rows, edit=tpl)


def _template_from_form(tpl):
    form = request.form
    errors = []
    name = form.get("name", "").strip()
    if not name:
        errors.append("Template name is required.")
    for field in ("background_color", "panel_color", "text_color"):
        if not HEX_RE.match(form.get(field, "")):
            errors.append(f"{field.replace('_', ' ').title()} must be a hex colour like #1E395E.")
    style = form.get("corner_style", "rounded")
    if style not in ("square", "rounded", "custom"):
        errors.append("Invalid corner style.")

    def _clamp(field, default, lo, hi):
        try:
            return max(lo, min(hi, int(form.get(field, str(default)))))
        except (TypeError, ValueError):
            return default

    radius = _clamp("corner_radius_px", 120, 0, 300)
    inner_radius = _clamp("inner_corner_radius_px", 30, 0, 300)
    qr_size = _clamp("qr_size_px", 980, 400, 1050)
    cta_y = _clamp("cta_baseline_y", 1320, 1150, 1640)
    url_y = _clamp("url_baseline_y", 1480, 1150, 1640)

    if not errors:
        tpl.name = name
        tpl.background_color = form.get("background_color").upper()
        tpl.panel_color = form.get("panel_color").upper()
        tpl.text_color = form.get("text_color").upper()
        tpl.corner_style = style
        tpl.corner_radius_px = radius
        tpl.inner_corner_radius_px = inner_radius
        tpl.qr_size_px = qr_size
        tpl.cta_baseline_y = cta_y
        tpl.url_baseline_y = url_y
        tpl.default_cta_text = form.get("default_cta_text", "").strip() or "Scan for more info!"
        tpl.is_default = form.get("is_default") == "on"
        tpl.is_active = form.get("is_active", "on") == "on"
    return tpl, errors


@bp.route("/templates/<int:tpl_id>", methods=["POST"])
@login_required
@role_required("admin")
def toggle_template(tpl_id):
    tpl = db.session.get(CardTemplate, tpl_id) or abort(404)
    tpl.is_active = not tpl.is_active
    db.session.commit()
    return redirect(url_for("admin.templates"))


# ── Bitly domains ────────────────────────────────────────────────────────
@bp.route("/domains", methods=["GET", "POST"])
@login_required
@role_required("admin")
def domains():
    if request.method == "POST":
        domain = request.form.get("domain", "").strip().lower()
        domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
        if not domain or "." not in domain:
            flash("Enter a domain like example.co (no https://).", "danger")
        elif BitlyDomain.query.filter_by(domain=domain).first():
            flash("That domain is already configured.", "warning")
        else:
            row = BitlyDomain(domain=domain, is_default=request.form.get("is_default") == "on")
            db.session.add(row)
            if row.is_default:
                BitlyDomain.query.filter(BitlyDomain.domain != domain).update(
                    {BitlyDomain.is_default: False}
                )
            db.session.commit()
            flash(f"Domain {domain} added.", "success")
        return redirect(url_for("admin.domains"))
    rows = BitlyDomain.query.order_by(BitlyDomain.domain).all()
    return render_template("admin/domains.html", domains=rows)


@bp.route("/domains/<int:domain_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_domain(domain_id):
    row = db.session.get(BitlyDomain, domain_id) or abort(404)
    action = request.form.get("action")
    if action == "toggle":
        row.is_active = not row.is_active
    elif action == "default":
        BitlyDomain.query.update({BitlyDomain.is_default: False})
        row.is_default = True
    db.session.commit()
    return redirect(url_for("admin.domains"))


# ── App settings ─────────────────────────────────────────────────────────
@bp.route("/settings", methods=["GET", "POST"])
@login_required
@role_required("admin")
def settings():
    if request.method == "POST":
        for key in SETTING_DEFAULTS:
            if key in request.form:
                set_setting(key, request.form[key].strip())
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    values = {k: get_setting(k) for k in SETTING_DEFAULTS}
    return render_template(
        "admin/settings.html", values=values, descriptions=SETTING_DESCRIPTIONS
    )


# ── Branding (v2.5): site logo upload ────────────────────────────────────
@bp.route("/settings/branding", methods=["POST"])
@login_required
@role_required("admin")
def branding():
    if request.form.get("remove_logo") == "on":
        set_setting("site_logo_filename", "")
        flash("Site logo removed.", "success")
        return redirect(url_for("admin.settings"))
    file = request.files.get("site_logo")
    if not file or not file.filename:
        flash("Choose an image file to upload.", "danger")
        return redirect(url_for("admin.settings"))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_LOGO_EXT:
        flash("Allowed formats: PNG, JPG, SVG.", "danger")
    elif not _content_ok(file, ext):
        flash("The file content does not match its extension.", "danger")
    else:
        filename = f"site_{uuid.uuid4().hex}{ext}"
        os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
        file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
        set_setting("site_logo_filename", filename)
        flash("Site logo updated.", "success")
    return redirect(url_for("admin.settings"))


# ── Troubleshooting (v2.5): manual job triggers ──────────────────────────
@bp.route("/troubleshoot/harvest", methods=["POST"])
@login_required
@role_required("admin")
def trigger_harvest():
    """Run the Bitly analytics harvest immediately (normally hourly)."""
    from ..models import LinkClick

    before = LinkClick.query.count()
    harvest_all(current_app._get_current_object())
    after = LinkClick.query.count()
    flash(f"Harvest complete: {after - before} new click record(s) ({after} total).", "success")
    return redirect(url_for("admin.settings"))


@bp.route("/troubleshoot/cleanup", methods=["POST"])
@login_required
@role_required("admin")
def trigger_cleanup():
    """Run the file/analytics retention cleanup immediately (normally daily)."""
    cleanup_retention(current_app._get_current_object())
    flash("Retention cleanup complete. Details are in the application log.", "success")
    return redirect(url_for("admin.settings"))


# ── All history ──────────────────────────────────────────────────────────
@bp.route("/history")
@login_required
@role_required("admin")
def history():
    rows = QRCode.query.order_by(QRCode.created_at.desc()).limit(500).all()
    return render_template("admin/history.html", rows=rows)


# ── QR design settings ───────────────────────────────────────────────────────
@bp.route("/qr-design", methods=["GET", "POST"])
@login_required
@role_required("admin")
def qr_design():
    if request.method == "POST":
        method = request.form.get("qr_method", "qrcode_monkey")
        if method not in ("qrcode_monkey", "local"):
            method = "qrcode_monkey"
        style = _parse_form_to_style(request.form)
        set_setting("qr_method", method)
        set_setting("qr_style_json", json.dumps(style))
        flash("QR design settings saved.", "success")
        return redirect(url_for("admin.qr_design"))

    qr_method = get_setting("qr_method") or "qrcode_monkey"
    qr_style = _load_qr_style()
    return render_template(
        "admin/qr_design.html",
        qr_method=qr_method,
        s=qr_style,
        body_shapes=BODY_SHAPES,
        eye_frames=EYE_FRAMES,
        eye_balls=EYE_BALLS,
        eye_transforms=EYE_TRANSFORMS,
        eye_keys=_EYE_KEYS,
    )


@bp.route("/qr-design/preview", methods=["POST"])
@login_required
@role_required("admin")
def qr_design_preview():
    """Return a small PNG preview of the current form state (not yet saved)."""
    from ..services import qr_local, qr_monkey as qrm

    method = request.form.get("qr_method", "qrcode_monkey")
    style = _parse_form_to_style(request.form)
    preview_url = (request.form.get("preview_url") or "https://qrstandards.com").strip()
    if not preview_url:
        preview_url = "https://qrstandards.com"

    try:
        if method == "local":
            content, _ = qr_local.generate(preview_url, "png", 400, style=style)
        else:
            content, _ = qrm.generate(preview_url, "png", 400, style=style)
    except (qr_local.QRLocalError, qrm.QRMonkeyError) as exc:
        return str(exc), 502

    return Response(content, mimetype="image/png")
