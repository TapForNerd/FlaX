from urllib.parse import urlencode

import json

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
import requests

from app.blueprints.auth.decorators import login_required
from app.blueprints.auth.token_helpers import call_x_api_with_refresh
from app.blueprints.x_api.commands import x_api_cli
from app.blueprints.x_api.helpers import (
    EXPANSIONS,
    TWEET_FIELDS,
    USER_FIELDS,
    _filter_fields,
    get_api_request_history,
    get_my_x_user,
    get_x_user_by_id,
    get_x_user_by_username,
    get_x_users_by_ids,
    get_x_users_by_usernames,
)
from app.models import ApiRequestLog
from app.models import UserLinkedAccount

bp = Blueprint("x_api", __name__, url_prefix="/x")
bp.cli.add_command(x_api_cli)


@bp.route("/")
@login_required
def index():
    response = call_x_api_with_refresh(
        requests.get,
        f"{current_app.config['X_API_BASE_URL']}/users/me",
        timeout=10,
        params={"user.fields": "id,name,username,created_at"},
    )
    if isinstance(response, dict):
        payload = response
    else:
        payload = {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get("Content-Type", "").startswith("application/json") else response.text,
        }
    linked_accounts = UserLinkedAccount.query.filter_by(
        owner_user_id=session["user_id"]
    ).all()
    return render_template(
        "home.html",
        app_name=current_app.config["APP_NAME"],
        x_response=payload,
        linked_accounts=linked_accounts,
        active_x_user_id=session.get("active_x_user_id"),
    )


@bp.route("/users", methods=["GET", "POST"])
@login_required
def users():
    username = ""
    usernames = ""
    user_id = ""
    user_ids = ""
    result = None
    error = session.get("x_user_lookup_error")
    curl_preview = session.get("x_user_lookup_curl")
    log_id = session.get("x_user_lookup_log_id")
    if log_id:
        log = ApiRequestLog.query.get(log_id)
        if log and log.response_body:
            try:
                result = json.loads(log.response_body)
            except json.JSONDecodeError:
                result = {"raw": log.response_body}
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        usernames = request.form.get("usernames", "").strip()
        user_id = request.form.get("user_id", "").strip()
        user_ids = request.form.get("user_ids", "").strip()
        curl_preview = None
        params = {
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
            "expansions": ",".join(_filter_fields(EXPANSIONS)),
            "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
        }

        def build_curl(url: str, params_dict: dict) -> str:
            query = urlencode(params_dict, safe=",")
            return f'curl -H "Authorization: Bearer <token>" "{url}?{query}"'
        if request.form.get("get_me"):
            flash("Lookup started.", "info")
            response = get_my_x_user()
            curl_preview = build_curl("https://api.x.com/2/users/me", params)
        elif username:
            flash("Lookup started.", "info")
            response = get_x_user_by_username(username)
            curl_preview = build_curl("https://api.x.com/2/users/by/username/<USERNAME>", params)
        elif usernames:
            cleaned = [name.strip() for name in usernames.split(",") if name.strip()]
            flash("Lookup started.", "info")
            response = get_x_users_by_usernames(cleaned)
            params["usernames"] = "USERNAME1,USERNAME2"
            curl_preview = build_curl("https://api.x.com/2/users/by", params)
        elif user_id:
            flash("Lookup started.", "info")
            response = get_x_user_by_id(user_id)
            curl_preview = build_curl("https://api.x.com/2/users/<ID>", params)
        elif user_ids:
            cleaned = [item.strip() for item in user_ids.split(",") if item.strip()]
            flash("Lookup started.", "info")
            response = get_x_users_by_ids(cleaned)
            params["ids"] = "ID1,ID2"
            curl_preview = build_curl("https://api.x.com/2/users", params)
        else:
            response = None
            error = "Please enter a username or id (single or comma-separated)."
            flash("Please enter a username or id first.", "warning")

        if response is None and error is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        elif response is not None:
            try:
                result = response.json()
            except ValueError:
                result = {"raw": response.text}
            if response.status_code and response.status_code >= 400:
                flash(f"Lookup failed with status {response.status_code}.", "danger")
            else:
                flash("Lookup complete.", "success")

        session["x_user_lookup_log_id"] = session.get("x_last_api_log_id")
        session["x_user_lookup_error"] = error
        session["x_user_lookup_curl"] = curl_preview
        return redirect(url_for("x_api.users"))

    return render_template(
        "x_api/users.html",
        username=username,
        usernames=usernames,
        user_id=user_id,
        user_ids=user_ids,
        result=result,
        error=error,
        curl_preview=curl_preview,
    )


@bp.route("/history")
@login_required
def history():
    logs = get_api_request_history()
    return render_template("x_api/history.html", logs=logs)
