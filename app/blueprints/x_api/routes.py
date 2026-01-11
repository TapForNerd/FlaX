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
    get_x_muted_users,
    get_x_user_by_id,
    get_x_user_by_username,
    get_x_users_by_ids,
    get_x_users_search,
    get_x_users_by_usernames,
    mute_x_user,
    resolve_x_user_id,
    unmute_x_user,
)
from app.models import ApiRequestLog, UserOAuthToken, XUser
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
    search_query = ""
    search_max_results = ""
    search_next_token = ""
    mute_target_id = ""
    mute_target_select = ""
    mute_max_results = ""
    mute_pagination_token = ""
    result = None
    error = session.get("x_user_lookup_error")
    curl_preview = session.get("x_user_lookup_curl")
    log_id = session.get("x_user_lookup_log_id")
    token_scope = None
    if log_id:
        log = ApiRequestLog.query.get(log_id)
        if log and log.response_body:
            body = log.response_body
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                result = None
                if body.startswith('"') and body.endswith('"'):
                    try:
                        unescaped = json.loads(body)
                        if isinstance(unescaped, str) and unescaped.lstrip().startswith(("{", "[")):
                            result = json.loads(unescaped)
                    except json.JSONDecodeError:
                        result = None
                if result is None:
                    result = {"raw": body}
        if isinstance(result, dict) and isinstance(result.get("raw"), str):
            raw_payload = result["raw"].lstrip()
            if raw_payload.startswith(("{", "[")):
                try:
                    result = json.loads(raw_payload)
                except json.JSONDecodeError:
                    pass

    owner_user_id = session.get("user_id")
    active_x_user_id = session.get("active_x_user_id")
    if owner_user_id:
        token = None
        if active_x_user_id:
            token = UserOAuthToken.query.filter_by(
                owner_user_id=owner_user_id, x_user_id=active_x_user_id
            ).first()
        if token is None:
            token = UserOAuthToken.query.filter_by(owner_user_id=owner_user_id).first()
        if token and token.scope:
            token_scope = token.scope

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        usernames = request.form.get("usernames", "").strip()
        user_id = request.form.get("user_id", "").strip()
        user_ids = request.form.get("user_ids", "").strip()
        search_query = request.form.get("search_query", "").strip()
        search_max_results = request.form.get("search_max_results", "").strip()
        search_next_token = request.form.get("search_next_token", "").strip()
        mute_target_id = request.form.get("mute_target_id", "").strip()
        mute_target_select = request.form.get("mute_target_select", "").strip()
        mute_max_results = request.form.get("mute_max_results", "").strip()
        mute_pagination_token = request.form.get("mute_pagination_token", "").strip()
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
        elif search_query:
            try:
                max_results = int(search_max_results) if search_max_results else 100
            except ValueError:
                max_results = 100
            max_results = min(max(max_results, 1), 1000)
            flash("Search started.", "info")
            response = get_x_users_search(search_query, max_results=max_results, next_token=search_next_token or None)
            params["query"] = "<QUERY>"
            params["max_results"] = max_results
            if search_next_token:
                params["next_token"] = "<NEXT_TOKEN>"
            curl_preview = build_curl("https://api.x.com/2/users/search", params)
        elif request.form.get("mute_action"):
            action = request.form.get("mute_action")
            if action in {"mute", "unmute"} and not (mute_target_id or mute_target_select):
                response = None
                error = "Please enter a user ID to mute/unmute."
                flash("Please enter a user ID first.", "warning")
            else:
                if not mute_target_id:
                    mute_target_id = mute_target_select
                resolved_id, resolve_error = resolve_x_user_id(mute_target_id)
                if resolve_error:
                    response = None
                    error = resolve_error
                    flash(resolve_error, "warning")
                else:
                    mute_target_id = resolved_id or mute_target_id
                if action == "mute":
                    flash("Mute started.", "info")
                    response = mute_x_user(mute_target_id)
                    curl_preview = (
                        'curl -X POST -H "Authorization: Bearer <token>" '
                        '-H "Content-Type: application/json" '
                        '"https://api.x.com/2/users/<ME>/muting" '
                        "-d '{\"target_user_id\":\"<TARGET_ID>\"}'"
                    )
                elif action == "unmute":
                    flash("Unmute started.", "info")
                    response = unmute_x_user(mute_target_id)
                    curl_preview = (
                        'curl -X DELETE -H "Authorization: Bearer <token>" '
                        '"https://api.x.com/2/users/<ME>/muting/<TARGET_ID>"'
                    )
                else:
                    try:
                        max_results = int(mute_max_results) if mute_max_results else 100
                    except ValueError:
                        max_results = 100
                    max_results = min(max(max_results, 1), 1000)
                    flash("Mute list started.", "info")
                    response = get_x_muted_users(
                        max_results=max_results,
                        pagination_token=mute_pagination_token or None,
                    )
                    mute_params = {
                        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                        "max_results": max_results,
                    }
                    if mute_pagination_token:
                        mute_params["pagination_token"] = "<PAGINATION_TOKEN>"
                    curl_preview = build_curl("https://api.x.com/2/users/<ME>/muting", mute_params)
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
        search_query=search_query,
        search_max_results=search_max_results,
        search_next_token=search_next_token,
        mute_target_id=mute_target_id,
        mute_target_select=mute_target_select,
        mute_max_results=mute_max_results,
        mute_pagination_token=mute_pagination_token,
        result=result,
        error=error,
        curl_preview=curl_preview,
        token_scope=token_scope,
        existing_users=XUser.query.order_by(XUser.username.asc()).limit(200).all(),
    )


@bp.route("/history")
@login_required
def history():
    logs = get_api_request_history()
    return render_template("x_api/history.html", logs=logs)
