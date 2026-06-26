"""SQLAlchemy models — DESIGN.md v2.3 §6."""
from datetime import datetime, timezone

from flask_login import UserMixin

from . import db


def utcnow():
    return datetime.now(timezone.utc)


ROLES = ("no_access", "user", "reporter", "admin")
ROLE_ORDER = {r: i for i, r in enumerate(ROLES)}


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255))
    display_name = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=True)  # NULL for LDAP users
    auth_type = db.Column(db.String(10), nullable=False, default="local")
    role = db.Column(db.String(20), nullable=False, default="no_access")
    can_custom_backhalves = db.Column(db.Boolean, nullable=False, default=False)
    default_logo_id = db.Column(db.Integer, db.ForeignKey("logos.id"), nullable=True)
    # §11 /preferences lists "preferred card template" — column added to
    # support it (small addition relative to the §6 schema).
    default_card_template_id = db.Column(
        db.Integer, db.ForeignKey("card_templates.id"), nullable=True
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    force_password_reset = db.Column(db.Boolean, nullable=False, default=False)
    session_expiry_days = db.Column(db.Integer, nullable=True)  # NULL = global
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login = db.Column(db.DateTime)

    def role_at_least(self, role):
        return ROLE_ORDER.get(self.role, 0) >= ROLE_ORDER[role]

    @property
    def label(self):
        return self.display_name or self.username


class Logo(db.Model):
    __tablename__ = "logos"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    filename = db.Column(db.String(512), nullable=False)
    is_global_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    # §8.2: cached QRCode Monkey uploaded-image token so the same logo is
    # not re-uploaded on every generation. Refreshed if the API rejects it.
    qrm_token = db.Column(db.String(255), nullable=True)
    qrm_token_at = db.Column(db.DateTime, nullable=True)


class BitlyDomain(db.Model):
    __tablename__ = "bitly_domains"

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class CardTemplate(db.Model):
    __tablename__ = "card_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    background_color = db.Column(db.String(7), nullable=False, default="#1E395E")
    panel_color = db.Column(db.String(7), nullable=False, default="#FFFFFF")
    text_color = db.Column(db.String(7), nullable=False, default="#FFFFFF")
    corner_style = db.Column(db.String(10), nullable=False, default="rounded")
    # Outer card corner radius (px). Inner panel radius is now independent
    # (was auto = outer - frame) so admins can tune both corners. §9.3
    corner_radius_px = db.Column(db.Integer, nullable=False, default=120)
    inner_corner_radius_px = db.Column(db.Integer, nullable=False, default=60)
    # QR size (px) centred within the white panel frame. §9.2
    qr_size_px = db.Column(db.Integer, nullable=False, default=980)
    # Vertical baseline (px from the top of the 1650-px card) for each text
    # line. Admins slide these up/down to taste. §9.2/§9.4
    cta_baseline_y = db.Column(db.Integer, nullable=False, default=1320)
    url_baseline_y = db.Column(db.Integer, nullable=False, default=1480)
    default_cta_text = db.Column(
        db.String(255), nullable=False, default="Scan for more info!"
    )
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def effective_radius(self):
        """Outer card corner radius after applying the corner style."""
        if self.corner_style == "square":
            return 0
        return self.corner_radius_px

    @property
    def effective_inner_radius(self):
        """Inner panel corner radius after applying the corner style."""
        if self.corner_style == "square":
            return 0
        return self.inner_corner_radius_px


class QRCode(db.Model):
    __tablename__ = "qr_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    generation_mode = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    long_url = db.Column(db.Text, nullable=False)
    short_url = db.Column(db.String(255), nullable=True)
    bitly_id = db.Column(db.String(100), nullable=True)
    bitly_domain_id = db.Column(
        db.Integer, db.ForeignKey("bitly_domains.id"), nullable=True
    )
    custom_backhalf = db.Column(db.String(120), nullable=True)
    cta_text = db.Column(db.String(255), nullable=True)
    card_template_id = db.Column(
        db.Integer, db.ForeignKey("card_templates.id"), nullable=True
    )
    logo_id = db.Column(db.Integer, db.ForeignKey("logos.id"), nullable=True)
    qr_config_json = db.Column(db.Text, nullable=True)
    zip_path = db.Column(db.String(512), nullable=True)
    png_path = db.Column(db.String(512), nullable=True)
    svg_path = db.Column(db.String(512), nullable=True)
    qr_png_path = db.Column(db.String(512), nullable=True)
    qr_svg_path = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship("User", backref="qr_codes")
    clicks = db.relationship(
        "LinkClick", backref="qr_code", cascade="all, delete-orphan"
    )

    @property
    def click_count(self):
        return LinkClick.query.filter_by(qr_code_id=self.id).count()


class LinkClick(db.Model):
    __tablename__ = "link_clicks"

    id = db.Column(db.Integer, primary_key=True)
    qr_code_id = db.Column(
        db.Integer, db.ForeignKey("qr_codes.id"), nullable=False, index=True
    )
    clicked_at = db.Column(db.DateTime, nullable=False, index=True)
    country = db.Column(db.String(5))
    city = db.Column(db.String(120))
    device_type = db.Column(db.String(50))
    os = db.Column(db.String(50))
    browser = db.Column(db.String(50))
    referrer = db.Column(db.String(512))
    raw_json = db.Column(db.Text)
    harvested_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(120), primary_key=True)
    value = db.Column(db.Text)


SETTING_DEFAULTS = {
    "site_title": "QRS Helper",
    "site_subtitle": "QR & Shortlink Generator",
    "session_expiry_days": "0",
    "file_retention_days": "365",
    "open_registration": "false",
    "allow_bitly_default_domain": "false",
    "analytics_harvest_interval_min": "60",
    "analytics_retention_days": "365",
}

SETTING_DESCRIPTIONS = {
    "site_title": "Title shown in the menu bar (Bebas Neue).",
    "site_subtitle": "Subtitle shown under the title in the menu bar.",
    "session_expiry_days": "Global session expiry in days. 0 = never expire.",
    "file_retention_days": "Days to keep generated files on disk. 0 = keep forever.",
    "open_registration": "Allow self-registration (true/false). New users get the no_access role.",
    "allow_bitly_default_domain": "If false, users may only use branded domains (true/false).",
    "analytics_harvest_interval_min": "Minutes between Bitly analytics harvests. Restart required to apply.",
    "analytics_retention_days": "Minimum days of click data to retain. 0 = keep forever.",
}


def get_setting(key):
    row = db.session.get(AppSetting, key)
    if row is not None and row.value is not None:
        return row.value
    return SETTING_DEFAULTS.get(key)


def get_setting_int(key):
    try:
        return int(get_setting(key))
    except (TypeError, ValueError):
        return int(SETTING_DEFAULTS.get(key, "0"))


def get_setting_bool(key):
    return str(get_setting(key)).strip().lower() in ("true", "1", "yes", "on")


def set_setting(key, value):
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=str(value))
        db.session.add(row)
    else:
        row.value = str(value)
    db.session.commit()
