"""Stats blueprint: dashboard, drill-down, CSV export — §11, Appendix B.

Users see their own data; reporters and admins see everything (§7.5).
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import db
from ..models import LinkClick, QRCode, User
from ..utils import role_required

bp = Blueprint("stats", __name__)


def _scope_filter(query, own_only=False):
    """Restrict to own records unless reporter+ (or forced via ?scope=me)."""
    if current_user.role_at_least("reporter") and not own_only:
        return query
    return query.filter(QRCode.user_id == current_user.id)


def _click_query(qr_id=None, own_only=False):
    q = db.session.query(LinkClick).join(QRCode)
    if qr_id is not None:
        q = q.filter(LinkClick.qr_code_id == qr_id)
    if own_only or not current_user.role_at_least("reporter"):
        q = q.filter(QRCode.user_id == current_user.id)
    return q


def _dashboard_data(qr_id=None, own_only=False):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    day = func.date(LinkClick.clicked_at)
    trend = (
        _click_query(qr_id, own_only)
        .filter(LinkClick.clicked_at >= since)
        .with_entities(day.label("d"), func.count(LinkClick.id))
        .group_by("d")
        .order_by("d")
        .all()
    )

    def grouped(col):
        return (
            _click_query(qr_id, own_only)
            .with_entities(col, func.count(LinkClick.id))
            .group_by(col)
            .order_by(func.count(LinkClick.id).desc())
            .limit(10)
            .all()
        )

    return {
        "trend_labels": [str(r[0]) for r in trend],
        "trend_values": [r[1] for r in trend],
        "devices": [[r[0] or "unknown", r[1]] for r in grouped(LinkClick.device_type)],
        "countries": [[r[0] or "unknown", r[1]] for r in grouped(LinkClick.country)],
        "referrers": [[r[0] or "direct", r[1]] for r in grouped(LinkClick.referrer)],
    }


@bp.route("/")
@login_required
@role_required("user")
def index():
    # v2.5: ?scope=me lets reporters/admins view just their own data
    own_only = request.args.get("scope") == "me"
    links = (
        _scope_filter(db.session.query(QRCode), own_only)
        .filter(QRCode.bitly_id.isnot(None))
        .order_by(QRCode.created_at.desc())
        .all()
    )
    total_clicks = _click_query(own_only=own_only).count()
    return render_template(
        "stats/index.html",
        data=_dashboard_data(own_only=own_only),
        links=links,
        total_clicks=total_clicks,
        scope_all=current_user.role_at_least("reporter") and not own_only,
        scope_me=own_only,
    )


@bp.route("/link/<int:qr_id>")
@login_required
@role_required("user")
def link_detail(qr_id):
    record = db.session.get(QRCode, qr_id) or abort(404)
    if record.user_id != current_user.id and not current_user.role_at_least("reporter"):
        abort(403)
    clicks = (
        LinkClick.query.filter_by(qr_code_id=qr_id)
        .order_by(LinkClick.clicked_at.desc())
        .limit(500)
        .all()
    )
    return render_template(
        "stats/detail.html", r=record, data=_dashboard_data(qr_id), clicks=clicks
    )


@bp.route("/export.csv")
@bp.route("/export/<int:qr_id>.csv")
@login_required
@role_required("user")
def export_csv(qr_id=None):
    """CSV export — Appendix B. Full export needs reporter; single link
    export is allowed for the record's owner."""
    q = (
        db.session.query(QRCode, User.username, func.count(LinkClick.id),
                         func.max(LinkClick.clicked_at))
        .join(User, QRCode.user_id == User.id)
        .outerjoin(LinkClick, LinkClick.qr_code_id == QRCode.id)
        .group_by(QRCode.id, User.username)
        .order_by(QRCode.created_at.desc())
    )
    if qr_id is not None:
        record = db.session.get(QRCode, qr_id) or abort(404)
        if record.user_id != current_user.id and not current_user.role_at_least("reporter"):
            abort(403)
        q = q.filter(QRCode.id == qr_id)
    elif not current_user.role_at_least("reporter"):
        q = q.filter(QRCode.user_id == current_user.id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["ID", "Title", "Mode", "Short URL", "Long URL", "Created",
         "Created By", "Total Clicks", "Last Click"]
    )
    for qr, username, clicks, last_click in q.all():
        writer.writerow(
            [
                qr.id,
                qr.title,
                qr.generation_mode,
                qr.short_url or "",
                qr.long_url,
                qr.created_at.isoformat() if qr.created_at else "",
                username,
                clicks,
                last_click.isoformat() if last_click else "",
            ]
        )
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=qr_stats_export.csv"},
    )
