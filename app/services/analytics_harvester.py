"""Scheduled Bitly analytics harvest + retention cleanup — DESIGN.md §12.4.

Bitly's free tier exposes per-unit click counts rather than a raw event
stream, so the harvester expands each hourly bucket into individual
link_clicks rows (one row per click, clicked_at = bucket timestamp).
Duplicate prevention: for each bucket we only insert the difference between
Bitly's count and the rows already stored for that qr_code_id + clicked_at.
"""
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from .. import db
from ..models import LinkClick, QRCode, get_setting_int
from . import bitly


def _parse_bitly_ts(value):
    # Bitly returns e.g. "2026-06-12T00:00:00+0000"
    if value.endswith("+0000"):
        value = value[:-5] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=None) if dt.tzinfo else dt  # store naive UTC


def harvest_all(app):
    with app.app_context():
        records = QRCode.query.filter(QRCode.bitly_id.isnot(None)).all()
        for qr in records:
            try:
                _harvest_one(qr)
            except bitly.BitlyError as exc:
                app.logger.warning("Harvest skipped for qr %s: %s", qr.id, exc)
                if "rate limit" in str(exc).lower():
                    break  # stop the run; try again next interval
            except Exception:  # noqa: BLE001 — never crash the app (§12.4)
                app.logger.exception("Harvest error for qr %s", qr.id)
            time.sleep(1.2)  # space requests well under 1,000 calls/hour (§8.1)


def _harvest_one(qr):
    data = bitly.get_clicks(qr.bitly_id, unit="hour", units=-1)
    for bucket in data.get("link_clicks", []):
        clicks = int(bucket.get("clicks", 0))
        if clicks <= 0:
            continue
        ts = _parse_bitly_ts(bucket["date"])
        existing = LinkClick.query.filter_by(qr_code_id=qr.id, clicked_at=ts).count()
        for _ in range(max(0, clicks - existing)):
            db.session.add(
                LinkClick(
                    qr_code_id=qr.id,
                    clicked_at=ts,
                    raw_json=json.dumps(bucket),
                )
            )
    db.session.commit()


def cleanup_retention(app):
    """Daily job: enforce file and analytics retention (§6.2 app_settings)."""
    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        file_days = get_setting_int("file_retention_days")
        if file_days > 0:
            cutoff = now - timedelta(days=file_days)
            old = QRCode.query.filter(
                QRCode.created_at < cutoff, QRCode.zip_path.isnot(None)
            ).all()
            out_root = app.config["OUTPUT_FOLDER"]
            for qr in old:
                rec_dir = os.path.join(out_root, f"qr_{qr.id}")
                if os.path.isdir(rec_dir):
                    shutil.rmtree(rec_dir, ignore_errors=True)
                qr.zip_path = qr.png_path = qr.svg_path = None
                qr.qr_png_path = qr.qr_svg_path = None
            db.session.commit()
            if old:
                app.logger.info("Retention: removed files for %d records", len(old))

        click_days = get_setting_int("analytics_retention_days")
        if click_days > 0:
            cutoff = now - timedelta(days=click_days)
            deleted = LinkClick.query.filter(LinkClick.clicked_at < cutoff).delete()
            db.session.commit()
            if deleted:
                app.logger.info("Retention: removed %d old click rows", deleted)
