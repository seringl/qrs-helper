"""Main blueprint: dashboard home, help page, site branding logo — v2.5."""
import os

from flask import Blueprint, abort, current_app, render_template, send_file
from flask_login import current_user, login_required

from .. import db
from ..models import LinkClick, QRCode, get_setting

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    """Dashboard: quick stats, recent items, quick-create shortcuts."""
    own = QRCode.query.filter_by(user_id=current_user.id)
    recent = own.order_by(QRCode.created_at.desc()).limit(5).all()
    my_count = own.count()
    my_clicks = (
        db.session.query(LinkClick)
        .join(QRCode)
        .filter(QRCode.user_id == current_user.id)
        .count()
    )
    return render_template(
        "main/dashboard.html", recent=recent, my_count=my_count, my_clicks=my_clicks
    )


@bp.route("/help")
@login_required
def help_page():
    return render_template("main/help.html")


@bp.route("/branding/logo")
def site_logo():
    """Serve the admin-uploaded site logo. Public: it appears on the
    login page navbar too. Filename is a server-generated UUID."""
    filename = get_setting("site_logo_filename")
    if not filename:
        abort(404)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path)
