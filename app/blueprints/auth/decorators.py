from functools import wraps

from flask import flash, redirect, session, url_for

from app.models import User


def _get_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)

    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = _get_user()
        if not user or not user.is_admin:
            flash("Admin access required.", "danger")
            return redirect(url_for("home.index"))
        return view_func(*args, **kwargs)

    return wrapper
