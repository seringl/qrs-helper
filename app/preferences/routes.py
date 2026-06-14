"""Preferences blueprint: password, display name, defaults — §11."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import bcrypt, db
from ..models import CardTemplate, Logo

bp = Blueprint("preferences", __name__)


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            display_name = request.form.get("display_name", "").strip()
            if display_name:
                current_user.display_name = display_name
            logo_id = request.form.get("default_logo_id", "")
            current_user.default_logo_id = int(logo_id) if logo_id.isdigit() else None
            tpl_id = request.form.get("default_card_template_id", "")
            current_user.default_card_template_id = (
                int(tpl_id) if tpl_id.isdigit() else None
            )
            db.session.commit()
            flash("Preferences saved.", "success")
        elif action == "password":
            if current_user.auth_type != "local":
                flash("Directory accounts manage passwords in the directory.", "warning")
            else:
                current_pw = request.form.get("current_password", "")
                new_pw = request.form.get("new_password", "")
                confirm = request.form.get("confirm", "")
                if not bcrypt.check_password_hash(
                    current_user.password_hash or "", current_pw
                ):
                    flash("Current password is incorrect.", "danger")
                elif len(new_pw) < 8:
                    flash("New password must be at least 8 characters.", "danger")
                elif new_pw != confirm:
                    flash("New passwords do not match.", "danger")
                else:
                    current_user.password_hash = bcrypt.generate_password_hash(
                        new_pw
                    ).decode()
                    db.session.commit()
                    flash("Password updated.", "success")
        return redirect(url_for("preferences.index"))

    return render_template(
        "preferences/index.html",
        logos=Logo.query.filter_by(is_active=True).order_by(Logo.name).all(),
        templates=CardTemplate.query.filter_by(is_active=True)
        .order_by(CardTemplate.name)
        .all(),
    )
