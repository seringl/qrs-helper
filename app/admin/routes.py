"""Admin blueprint: users, logos, card templates, domains, settings — §11."""
import os
import re
import uuid

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request,
    url_for,
)
from flask_login import current_user, login_required

from .. import bcrypt, db
from ..models import (
    ROLES, BitlyDomain, CardTemplate, Logo, QRCode, User,
    SETTING_DEFAULTS, SETTING_DESCRIPTIONS, get_setting, set_setting,
)
from ..services.analytics_harvester import cleanup_retention, harvest_all
from ..services.setup_service import _dinopass_password
from ..utils import role_required

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
    qr_size = _clamp("qr_size_px", 880, 400, 1050)
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
