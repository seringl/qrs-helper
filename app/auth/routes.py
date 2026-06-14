"""Auth blueprint: login (local + directory), register, logout, reset."""
from datetime import datetime, timezone

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from .. import bcrypt, db
from ..models import User, get_setting_bool, utcnow
from . import ldap_service

bp = Blueprint("auth", __name__)


def _finish_login(user):
    user.last_login = utcnow()
    db.session.commit()
    login_user(user)
    session["login_at"] = datetime.now(timezone.utc).isoformat()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    ldap_enabled = ldap_service.is_enabled()
    ldap_available = ldap_service.is_available() if ldap_enabled else False

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        method = request.form.get("auth_method", "local")

        if not username or not password:
            flash("Username and password are required.", "danger")
        elif method == "directory" and ldap_enabled:
            try:
                info = ldap_service.authenticate(username, password)
            except Exception:  # noqa: BLE001 — outage → §7.4 fallback message
                info = None
                flash(
                    "Directory login is currently unavailable. "
                    "Please use local credentials.",
                    "warning",
                )
            else:
                if info is None:
                    flash("Directory login failed: check your credentials.", "danger")
                else:
                    user = User.query.filter_by(
                        username=info["username"], auth_type="ldap"
                    ).first()
                    if user is None:
                        user = User(
                            username=info["username"],
                            auth_type="ldap",
                            role="user",  # §7.3 LDAP users default to `user`
                        )
                        db.session.add(user)
                    user.email = info.get("email") or user.email
                    user.display_name = info.get("display_name") or user.display_name
                    if not user.is_active:
                        flash("This account has been disabled.", "danger")
                    else:
                        _finish_login(user)
                        return redirect(url_for("main.index"))
        else:
            user = User.query.filter_by(username=username, auth_type="local").first()
            if (
                user is None
                or user.password_hash is None
                or not bcrypt.check_password_hash(user.password_hash, password)
            ):
                flash("Login failed: check your username and password.", "danger")
            elif not user.is_active:
                flash("This account has been disabled.", "danger")
            else:
                _finish_login(user)
                return redirect(url_for("main.index"))

    return render_template(
        "auth/login.html",
        ldap_enabled=ldap_enabled,
        ldap_available=ldap_available,
        open_registration=_open_registration(),
    )


def _open_registration():
    try:
        return get_setting_bool("open_registration")
    except Exception:  # noqa: BLE001 — tables may not exist on first boot
        return True


@bp.route("/register", methods=["GET", "POST"])
def register():
    if not _open_registration():
        flash("Self-registration is currently disabled.", "warning")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password or not display_name:
            flash("Username, display name, and password are required.", "danger")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("That username is already taken.", "danger")
        else:
            user = User(
                username=username,
                display_name=display_name,
                email=email,
                auth_type="local",
                role="no_access",  # §7.2 until promoted by an admin
                password_hash=bcrypt.generate_password_hash(password).decode(),
            )
            db.session.add(user)
            db.session.commit()
            flash(
                "Account created. An administrator must grant you access "
                "before you can create links or QR codes.",
                "success",
            )
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@bp.route("/reset-password", methods=["GET", "POST"])
@login_required
def reset_password():
    if current_user.auth_type != "local":
        flash("Directory accounts manage passwords in the directory.", "warning")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        else:
            current_user.password_hash = bcrypt.generate_password_hash(
                password
            ).decode()
            current_user.force_password_reset = False
            db.session.commit()
            # The initial-password file (if any) is now stale — remove it.
            from flask import current_app

            from ..services.setup_service import clear_password_file
            clear_password_file(current_app)
            flash("Password updated.", "success")
            return redirect(url_for("main.index"))

    return render_template(
        "auth/reset_password.html", forced=current_user.force_password_reset
    )


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
