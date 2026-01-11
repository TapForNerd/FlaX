from flask import Blueprint, current_app, render_template, session

from app.models import UserLinkedAccount

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    linked_accounts = []
    if session.get("user_id"):
        linked_accounts = UserLinkedAccount.query.filter_by(
            owner_user_id=session["user_id"]
        ).all()
    return render_template(
        "home.html",
        app_name=current_app.config["APP_NAME"],
        x_response=None,
        linked_accounts=linked_accounts,
        active_x_user_id=session.get("active_x_user_id"),
    )
