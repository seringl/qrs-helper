"""Application factory. See DESIGN.md v2.3."""
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from flask import Flask, redirect, request, session, url_for
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()
migrate = Migrate()


def create_app():
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    env = os.environ.get("FLASK_ENV", "production")
    is_dev = env == "development"

    app.config["ENV_NAME"] = env
    app.config["DEBUG"] = is_dev
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "dev-insecure-change-me"

    # §5/§6.1: DATABASE_URL is derived from instance_path when unset, so the
    # SQLite file always lands at <project-root>/instance/app.db regardless
    # of working directory.
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(app.instance_path, "app.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER") or os.path.join(
        app.instance_path, "uploads"
    )
    app.config["OUTPUT_FOLDER"] = os.environ.get("OUTPUT_FOLDER") or os.path.join(
        app.instance_path, "outputs"
    )
    app.config["MAX_CONTENT_LENGTH"] = (
        int(os.environ.get("MAX_UPLOAD_MB", "5")) * 1024 * 1024
    )
    app.config["BCRYPT_LOG_ROUNDS"] = 12  # §14.1

    # §14.2 Session cookie security. Secure flags are disabled in
    # development so the app can run without a TLS proxy.
    app.config["SESSION_COOKIE_SECURE"] = not is_dev
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["REMEMBER_COOKIE_SECURE"] = not is_dev
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"

    # §14.3 ProxyFix: required so request.scheme is correct behind nginx.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from . import models  # noqa: F401  (register models with SQLAlchemy)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    # Blueprints
    from .auth.routes import bp as auth_bp
    from .create.routes import bp as create_bp
    from .history.routes import bp as history_bp
    from .stats.routes import bp as stats_bp
    from .admin.routes import bp as admin_bp
    from .preferences.routes import bp as preferences_bp
    from .main.routes import bp as main_bp

    app.register_blueprint(main_bp)  # /, /help, /branding/logo
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(create_bp)  # /create, /result/<id>, /files/...
    app.register_blueprint(history_bp, url_prefix="/history")
    app.register_blueprint(stats_bp, url_prefix="/stats")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(preferences_bp, url_prefix="/preferences")

    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.context_processor
    def inject_branding():
        """v2.5: editable site title/subtitle/logo on every page."""
        try:
            title = models.get_setting("site_title") or "QRS Helper"
            subtitle = models.get_setting("site_subtitle") or "QR & Shortlink Generator"
            logo = models.get_setting("site_logo_filename")
        except Exception:  # tables may not exist on very first boot
            title, subtitle, logo = "QRS Helper", "QR & Shortlink Generator", None
        return {
            "site_title": title,
            "site_subtitle": subtitle,
            "site_logo_url": url_for("main.site_logo") if logo else None,
        }

    @app.before_request
    def _session_guard():
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return None
        if request.endpoint in ("static", None):
            return None

        # §7.2 session expiry: per-user override, else global setting; 0 = never
        days = current_user.session_expiry_days
        if days is None:
            days = models.get_setting_int("session_expiry_days")
        if days and days > 0:
            login_at = session.get("login_at")
            if login_at:
                started = datetime.fromisoformat(login_at)
                if datetime.now(timezone.utc) - started > timedelta(days=days):
                    logout_user()
                    session.clear()
                    return redirect(url_for("auth.login"))
            else:
                session["login_at"] = datetime.now(timezone.utc).isoformat()

        # §7.1 force password reset on first login
        allowed = ("auth.reset_password", "auth.logout", "healthz")
        if current_user.force_password_reset and request.endpoint not in allowed:
            return redirect(url_for("auth.reset_password"))
        return None

    @app.errorhandler(403)
    def forbidden(_e):
        from flask import render_template

        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_e):
        from flask import render_template

        return render_template("errors/404.html"), 404

    # First-run initialisation CLI (called by docker-entrypoint.sh)
    from .services.setup_service import initialize, reset_admin_password

    @app.cli.command("init-app")
    def init_app_command():
        """First run: create schema, dirs, admin account, seed data."""
        initialize(app)

    @app.cli.command("reset-admin-password")
    def reset_admin_password_command():
        """Reset the admin password and reprint it (recovery if it was missed)."""
        reset_admin_password(app)

    # §12.4 background scheduler (analytics harvest + retention cleanup)
    _maybe_start_scheduler(app)

    return app


def _maybe_start_scheduler(app):
    if app.testing or os.environ.get("ENABLE_SCHEDULER", "1") != "1":
        return
    # Avoid double-start under the dev server's reloader.
    if app.config["ENV_NAME"] == "development" and os.environ.get(
        "WERKZEUG_RUN_MAIN"
    ) != "true":
        return
    # Don't start the scheduler for one-off CLI commands (init-app, db, shell).
    import sys

    if any(a in sys.argv for a in ("init-app", "db", "shell")):
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    from .models import get_setting_int
    from .services.analytics_harvester import cleanup_retention, harvest_all

    with app.app_context():
        try:
            interval = get_setting_int("analytics_harvest_interval_min") or 60
        except Exception:
            interval = 60  # tables may not exist yet on very first boot

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        harvest_all, "interval", minutes=interval, args=[app], id="harvest",
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        cleanup_retention, "interval", hours=24, args=[app], id="cleanup",
        max_instances=1, coalesce=True,
    )
    scheduler.start()
    app.extensions["scheduler"] = scheduler
