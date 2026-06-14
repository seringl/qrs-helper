"""First-run initialisation — DESIGN.md §7.1 / §13.2.

Called by `flask init-app` from docker-entrypoint.sh. Idempotent:
safe to run on every container start.
"""
import os
import secrets

import requests
from sqlalchemy import inspect, text

from .. import bcrypt, db
from ..models import CardTemplate, User


def password_file_path(app):
    """Where the one-time initial admin password is written on first run."""
    return os.path.join(app.instance_path, "INITIAL_ADMIN_PASSWORD.txt")


def clear_password_file(app):
    """Remove the initial-password file (called once the admin resets it)."""
    try:
        os.remove(password_file_path(app))
    except OSError:
        pass


def _save_and_print_password(app, username, password, *, created):
    """Write the temporary password to a file and print a clear banner."""
    verb = "created" if created else "reset"
    try:
        with open(password_file_path(app), "w", encoding="utf-8") as fh:
            fh.write(
                "Initial admin account for QRS Helper\n"
                f"Username: {username}\n"
                f"Temporary password: {password}\n"
                "You must change this password on first login.\n"
                "This file is removed automatically after you do.\n"
            )
    except OSError:
        pass
    print("=" * 60)
    print(f"  Admin account {verb}: {username}")
    print(f"  Temporary password: {password}")
    print("  You will be required to change it on first login.")
    print(f"  Also saved to: {password_file_path(app)}")
    print("=" * 60)


def reset_admin_password(app):
    """Reset the admin account's password and re-announce it.

    Recovery path for when the initial password was missed (for example the
    database already existed on first run, so no new password was generated).
    Run with:  docker compose exec app flask reset-admin-password
    """
    with app.app_context():
        admin_username = os.environ.get("ADMIN_USERNAME", "qrsadmin")
        user = (
            User.query.filter_by(username=admin_username).first()
            or User.query.filter_by(role="admin").order_by(User.id).first()
        )
        if user is None:
            print("No admin account exists yet. Run `flask init-app` first.")
            return
        if user.auth_type != "local":
            print(
                f"Admin '{user.username}' is a directory account; its password "
                "is managed in the directory, not here."
            )
            return
        password = _dinopass_password()
        user.password_hash = bcrypt.generate_password_hash(password).decode()
        user.force_password_reset = True
        db.session.commit()
        _save_and_print_password(app, user.username, password, created=False)


def _dinopass_password():
    """§8.4: memorable password from Dinopass, with a local fallback."""
    try:
        r = requests.get("https://dinopass.com/password/simple", timeout=5)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()
    except requests.RequestException:
        pass
    return secrets.token_urlsafe(12)


# Columns added after the original schema. For demo/SQLite installs without a
# migrations/ tree, initialize() adds any that are missing so existing
# databases upgrade in place. (Production installs use `flask db upgrade`.)
_ADDED_COLUMNS = {
    "card_templates": {
        "inner_corner_radius_px": "INTEGER NOT NULL DEFAULT 30",
        "qr_size_px": "INTEGER NOT NULL DEFAULT 880",
        "cta_baseline_y": "INTEGER NOT NULL DEFAULT 1320",
        "url_baseline_y": "INTEGER NOT NULL DEFAULT 1480",
    },
    "logos": {
        "qrm_token": "VARCHAR(255)",
        "qrm_token_at": "DATETIME",
    },
}


def _ensure_columns():
    """Add post-v2.5 columns to existing tables when no migration tree exists."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all() will have built it with all columns
        present = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in present:
                db.session.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                )
                print(f"Schema upgrade: added {table}.{name}")
    db.session.commit()


def initialize(app):
    with app.app_context():
        # Runtime directories (instance/ is a mounted volume in Docker)
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)
        os.makedirs(os.path.join(app.instance_path, "ssl"), exist_ok=True)

        # Schema. (Flask-Migrate is configured; once a migrations/ tree is
        # initialised, `flask db upgrade` supersedes create_all.)
        db.create_all()
        _ensure_columns()

        # Initial admin account (§7.1)
        admin_username = os.environ.get("ADMIN_USERNAME", "qrsadmin")
        if User.query.filter_by(role="admin").count() == 0:
            existing = User.query.filter_by(username=admin_username).first()
            if existing is None:
                password = _dinopass_password()
                admin = User(
                    username=admin_username,
                    display_name="Administrator",
                    auth_type="local",
                    role="admin",
                    password_hash=bcrypt.generate_password_hash(password).decode(),
                    force_password_reset=True,
                    can_custom_backhalves=True,
                )
                db.session.add(admin)
                db.session.commit()
                # Persist to a file so the password can be retrieved reliably
                # even when the container is started detached (docker compose
                # up -d). It is deleted automatically once the admin resets it.
                _save_and_print_password(app, admin_username, password, created=True)
            else:
                existing.role = "admin"
                db.session.commit()
                print(f"Promoted existing user '{admin_username}' to admin.")
        else:
            print("Admin account already present; skipping.")

        # Seed one default card template so full-card mode works out of the box
        if CardTemplate.query.count() == 0:
            db.session.add(
                CardTemplate(
                    name="Standard",
                    background_color="#1E395E",
                    panel_color="#FFFFFF",
                    text_color="#FFFFFF",
                    corner_style="rounded",
                    corner_radius_px=120,
                    inner_corner_radius_px=30,
                    qr_size_px=880,
                    cta_baseline_y=1320,
                    url_baseline_y=1480,
                    default_cta_text="Scan for more info!",
                    is_default=True,
                )
            )
            db.session.commit()
            print("Seeded default card template 'Standard'.")

        print("Initialisation complete.")
