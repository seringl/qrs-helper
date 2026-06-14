"""Shared helpers: role-based access decorator (§7.5)."""
from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(min_role):
    """Use *after* @login_required. 403 if the user's role is below min_role."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.role_at_least(min_role):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
