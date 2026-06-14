"""History blueprint: own history; /all for reporters and admins."""
from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import db
from ..models import LinkClick, QRCode, User
from ..utils import role_required

bp = Blueprint("history", __name__)


def _with_click_counts(query):
    rows = (
        query.outerjoin(LinkClick, LinkClick.qr_code_id == QRCode.id)
        .add_columns(func.count(LinkClick.id).label("clicks"))
        .group_by(QRCode.id)
        .order_by(QRCode.created_at.desc())
        .all()
    )
    return rows  # list of (QRCode, clicks)


@bp.route("/")
@login_required
def index():
    rows = _with_click_counts(
        db.session.query(QRCode).filter(QRCode.user_id == current_user.id)
    )
    return render_template("history/index.html", rows=rows, all_users=False)


@bp.route("/all")
@login_required
@role_required("reporter")
def all_history():
    rows = _with_click_counts(db.session.query(QRCode).join(User))
    return render_template("history/index.html", rows=rows, all_users=True)
