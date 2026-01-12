from urllib.parse import urlencode

import json

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
import requests

from app.blueprints.auth.decorators import login_required
from app.blueprints.auth.token_helpers import call_x_api_with_refresh
from app.blueprints.x_api.commands import x_api_cli
from app.blueprints.x_api.helpers import (
    EXPANSIONS,
    COMMUNITY_FIELDS,
    LIST_EXPANSIONS,
    LIST_FIELDS,
    SPACE_EXPANSIONS,
    SPACE_FIELDS,
    TWEET_EXPANSIONS,
    TWEET_FIELDS,
    USER_FIELDS,
    _filter_fields,
    add_x_list_member,
    create_x_list,
    delete_x_list,
    follow_x_list,
    get_api_request_history,
    get_x_community_by_id,
    get_my_x_user,
    get_x_list_by_id,
    get_x_list_followers,
    get_x_list_members,
    get_x_list_tweets,
    get_x_liked_posts,
    get_x_liking_users,
    get_x_spaces_by_creator_ids,
    get_x_spaces_by_ids,
    get_x_space_posts,
    get_x_spaces_search,
    get_x_muted_users,
    get_x_users_by_ids_with_app_token,
    get_x_user_by_id,
    get_x_user_followed_lists,
    get_x_user_list_memberships,
    get_x_user_owned_lists,
    get_x_user_pinned_lists,
    get_x_user_by_username,
    get_x_users_by_ids,
    get_x_users_search,
    get_x_users_by_usernames,
    like_x_post,
    mute_x_user,
    pin_x_list,
    remove_x_list_member,
    resolve_x_user_id,
    resolve_x_post_id,
    search_x_communities,
    unmute_x_user,
    unfollow_x_list,
    unlike_x_post,
    unpin_x_list,
    update_x_list,
)
from app.models import ApiRequestLog, UserOAuthToken, XPost, XSpace, XUser
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
            if isinstance(response, dict):
                result = response
                if response.get("error"):
                    flash(response["error"], "warning")
                else:
                    flash("Lookup complete.", "success")
            else:
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


@bp.route("/likes", methods=["GET", "POST"])
@login_required
def likes():
    liked_user_identifier = ""
    liked_user_select = ""
    liked_max_results = ""
    liked_pagination_token = ""
    liking_post_identifier = ""
    liking_post_select = ""
    liking_max_results = ""
    liking_pagination_token = ""
    like_post_identifier = ""
    like_post_select = ""
    result = None
    error = session.get("x_likes_lookup_error")
    curl_preview = session.get("x_likes_lookup_curl")
    log_id = session.get("x_likes_lookup_log_id")
    known_limit = session.get("x_likes_known_limit")
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
        known_limit = None
        liked_user_identifier = request.form.get("liked_user_identifier", "").strip()
        liked_user_select = request.form.get("liked_user_select", "").strip()
        liked_max_results = request.form.get("liked_max_results", "").strip()
        liked_pagination_token = request.form.get("liked_pagination_token", "").strip()
        liking_post_identifier = request.form.get("liking_post_identifier", "").strip()
        liking_post_select = request.form.get("liking_post_select", "").strip()
        liking_max_results = request.form.get("liking_max_results", "").strip()
        liking_pagination_token = request.form.get("liking_pagination_token", "").strip()
        like_post_identifier = request.form.get("like_post_identifier", "").strip()
        like_post_select = request.form.get("like_post_select", "").strip()
        curl_preview = None

        def build_curl(url: str, params_dict: dict | None = None) -> str:
            if not params_dict:
                return f'curl -H "Authorization: Bearer <token>" "{url}"'
            query = urlencode(params_dict, safe=",")
            return f'curl -H "Authorization: Bearer <token>" "{url}?{query}"'

        action = request.form.get("likes_action")
        if action == "liked_posts":
            if not liked_user_identifier:
                liked_user_identifier = liked_user_select or session.get("active_x_user_id", "")
                if liked_user_identifier:
                    flash("Using your active X account for liked posts.", "info")
            resolved_id, resolve_error = resolve_x_user_id(liked_user_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                try:
                    max_results = int(liked_max_results) if liked_max_results else 100
                except ValueError:
                    max_results = 100
                max_results = min(max(max_results, 5), 100)
                flash("Likes lookup started.", "info")
                response = get_x_liked_posts(
                    resolved_id,
                    max_results=max_results,
                    pagination_token=liked_pagination_token or None,
                )
                params = {"max_results": max_results}
                if liked_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl(
                    "https://api.x.com/2/users/<USER_ID>/liked_tweets", params
                )
        elif action == "liking_users":
            if not liking_post_identifier:
                liking_post_identifier = liking_post_select
            resolved_id, resolve_error = resolve_x_post_id(liking_post_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                try:
                    max_results = int(liking_max_results) if liking_max_results else 100
                except ValueError:
                    max_results = 100
                max_results = min(max(max_results, 1), 100)
                flash("Liking users lookup started.", "info")
                response = get_x_liking_users(
                    resolved_id,
                    max_results=max_results,
                    pagination_token=liking_pagination_token or None,
                )
                params = {"max_results": max_results}
                if liking_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl(
                    "https://api.x.com/2/tweets/<POST_ID>/liking_users", params
                )
        elif action in {"like", "unlike"}:
            if not like_post_identifier:
                like_post_identifier = like_post_select
            resolved_id, resolve_error = resolve_x_post_id(like_post_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                if action == "like":
                    flash("Like started.", "info")
                    response = like_x_post(resolved_id)
                    curl_preview = (
                        'curl -X POST -H "Authorization: Bearer <token>" '
                        '-H "Content-Type: application/json" '
                        '"https://api.x.com/2/users/<ME>/likes" '
                        "-d '{\"tweet_id\":\"<POST_ID>\"}'"
                    )
                else:
                    flash("Unlike started.", "info")
                    response = unlike_x_post(resolved_id)
                    curl_preview = (
                        'curl -X DELETE -H "Authorization: Bearer <token>" '
                        '"https://api.x.com/2/users/<ME>/likes/<POST_ID>"'
                    )
        else:
            response = None
            error = "Please select a likes action to run."
            flash("Please select an action first.", "warning")

        if response is None and error is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        elif response is not None:
            def extract_problem(payload: dict) -> dict | None:
                if not isinstance(payload, dict):
                    return None
                if payload.get("type") or payload.get("title"):
                    return payload
                errors = payload.get("errors")
                if isinstance(errors, list) and errors:
                    return errors[0]
                return None

            if isinstance(response, dict):
                result = response
                problem = extract_problem(result)
                if problem and (
                    problem.get("type") == "https://api.twitter.com/2/problems/unsupported-authentication"
                    or problem.get("title") == "Unsupported Authentication"
                ):
                    known_limit = (
                        "X returned Unsupported Authentication for this endpoint. "
                        "Liking users requires OAuth user context and can be restricted by account access level."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.get("error"):
                    flash(response["error"], "warning")
                else:
                    flash("Lookup complete.", "success")
            else:
                try:
                    result = response.json()
                except ValueError:
                    result = {"raw": response.text}
                problem = extract_problem(result)
                if problem and (
                    problem.get("type") == "https://api.twitter.com/2/problems/unsupported-authentication"
                    or problem.get("title") == "Unsupported Authentication"
                ):
                    known_limit = (
                        "X returned Unsupported Authentication for this endpoint. "
                        "Liking users requires OAuth user context and can be restricted by account access level."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        session["x_likes_lookup_log_id"] = session.get("x_last_api_log_id")
        session["x_likes_lookup_error"] = error
        session["x_likes_lookup_curl"] = curl_preview
        session["x_likes_known_limit"] = known_limit
        return redirect(url_for("x_api.likes"))

    return render_template(
        "x_api/likes.html",
        liked_user_identifier=liked_user_identifier,
        liked_user_select=liked_user_select,
        liked_max_results=liked_max_results,
        liked_pagination_token=liked_pagination_token,
        liking_post_identifier=liking_post_identifier,
        liking_post_select=liking_post_select,
        liking_max_results=liking_max_results,
        liking_pagination_token=liking_pagination_token,
        like_post_identifier=like_post_identifier,
        like_post_select=like_post_select,
        result=result,
        error=error,
        curl_preview=curl_preview,
        known_limit=known_limit,
        token_scope=token_scope,
        existing_users=XUser.query.order_by(XUser.username.asc()).limit(200).all(),
        existing_posts=XPost.query.order_by(XPost.created_at.desc()).limit(200).all(),
    )


@bp.route("/communities", methods=["GET", "POST"])
@login_required
def communities():
    community_id = ""
    search_query = ""
    search_max_results = ""
    search_next_token = ""
    search_pagination_token = ""
    result = None
    error = session.get("x_communities_lookup_error")
    known_limit = session.get("x_communities_known_limit")
    curl_preview = session.get("x_communities_lookup_curl")
    log_id = session.get("x_communities_lookup_log_id")

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

    if request.method == "POST":
        known_limit = None
        community_id = request.form.get("community_id", "").strip()
        search_query = request.form.get("search_query", "").strip()
        search_max_results = request.form.get("search_max_results", "").strip()
        search_next_token = request.form.get("search_next_token", "").strip()
        search_pagination_token = request.form.get("search_pagination_token", "").strip()
        curl_preview = None

        def build_curl(url: str, params_dict: dict | None = None) -> str:
            if not params_dict:
                return f'curl -H "Authorization: Bearer <token>" "{url}"'
            query = urlencode(params_dict, safe=",")
            return f'curl -H "Authorization: Bearer <token>" "{url}?{query}"'

        action = request.form.get("communities_action")
        response = None
        if action == "community_by_id":
            if not community_id:
                error = "Please provide a Community ID."
                flash(error, "warning")
            else:
                flash("Community lookup started.", "info")
                response = get_x_community_by_id(community_id)
                params = {"community.fields": ",".join(_filter_fields(COMMUNITY_FIELDS))}
                curl_preview = build_curl("https://api.x.com/2/communities/<ID>", params)
        elif action == "search_communities":
            if not search_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                try:
                    max_results = int(search_max_results) if search_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 10), 100)
                flash("Community search started.", "info")
                response = search_x_communities(
                    search_query,
                    max_results=max_results,
                    next_token=search_next_token or None,
                    pagination_token=search_pagination_token or None,
                )
                params = {
                    "query": "<QUERY>",
                    "max_results": max_results,
                    "community.fields": ",".join(_filter_fields(COMMUNITY_FIELDS)),
                }
                if search_next_token:
                    params["next_token"] = "<NEXT_TOKEN>"
                if search_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/communities/search", params)
        else:
            response = None
            error = "Please select a communities action to run."
            flash("Please select an action first.", "warning")

        if response is None and error is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        elif response is not None:
            def extract_problem(payload: dict) -> dict | None:
                if not isinstance(payload, dict):
                    return None
                if payload.get("type") or payload.get("title"):
                    return payload
                errors = payload.get("errors")
                if isinstance(errors, list) and errors:
                    return errors[0]
                return None

            if isinstance(response, dict):
                result = response
                problem = extract_problem(result)
                if problem and (
                    problem.get("type") == "https://api.twitter.com/2/problems/unsupported-authentication"
                    or problem.get("title") == "Unsupported Authentication"
                ):
                    known_limit = (
                        "X returned Unsupported Authentication for this endpoint. "
                        "Community lookup requires OAuth user context."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.get("error"):
                    flash(response["error"], "warning")
                else:
                    flash("Lookup complete.", "success")
            else:
                try:
                    result = response.json()
                except ValueError:
                    result = {"raw": response.text}
                problem = extract_problem(result)
                if problem and (
                    problem.get("type") == "https://api.twitter.com/2/problems/unsupported-authentication"
                    or problem.get("title") == "Unsupported Authentication"
                ):
                    known_limit = (
                        "X returned Unsupported Authentication for this endpoint. "
                        "Community lookup requires OAuth user context."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        session["x_communities_lookup_log_id"] = session.get("x_last_api_log_id")
        session["x_communities_lookup_error"] = error
        session["x_communities_lookup_curl"] = curl_preview
        session["x_communities_known_limit"] = known_limit
        return redirect(url_for("x_api.communities"))

    return render_template(
        "x_api/communities.html",
        community_id=community_id,
        search_query=search_query,
        search_max_results=search_max_results,
        search_next_token=search_next_token,
        search_pagination_token=search_pagination_token,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
    )


@bp.route("/spaces", methods=["GET", "POST"])
@login_required
def spaces():
    space_search_query = ""
    space_search_state = ""
    space_search_max_results = ""
    space_search_next_token = ""
    space_ids = ""
    space_posts_id = ""
    space_posts_max_results = ""
    space_poll_id = ""
    creator_identifier = ""
    creator_user_select = ""
    result = None
    error = session.get("x_spaces_lookup_error")
    curl_preview = session.get("x_spaces_lookup_curl")
    log_id = session.get("x_spaces_lookup_log_id")

    def load_logged_result() -> dict | None:
        if not log_id:
            return None
        log = ApiRequestLog.query.get(log_id)
        if not log or not log.response_body:
            return None
        body = log.response_body
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
            if body.startswith('"') and body.endswith('"'):
                try:
                    unescaped = json.loads(body)
                    if isinstance(unescaped, str) and unescaped.lstrip().startswith(("{", "[")):
                        parsed = json.loads(unescaped)
                except json.JSONDecodeError:
                    parsed = None
            if parsed is None:
                parsed = {"raw": body}
        if isinstance(parsed, dict) and isinstance(parsed.get("raw"), str):
            raw_payload = parsed["raw"].lstrip()
            if raw_payload.startswith(("{", "[")):
                try:
                    parsed = json.loads(raw_payload)
                except json.JSONDecodeError:
                    pass
        return parsed

    if log_id:
        result = load_logged_result()

    existing_users = XUser.query.order_by(XUser.username.asc()).limit(200).all()
    known_users_by_id = {str(user.id): user for user in existing_users}

    if request.method == "POST":
        space_search_query = request.form.get("space_search_query", "").strip()
        space_search_state = request.form.get("space_search_state", "").strip()
        space_search_max_results = request.form.get("space_search_max_results", "").strip()
        space_search_next_token = request.form.get("space_search_next_token", "").strip()
        space_ids = request.form.get("space_ids", "").strip()
        space_posts_id = request.form.get("space_posts_id", "").strip()
        space_posts_max_results = request.form.get("space_posts_max_results", "").strip()
        space_poll_id = request.form.get("space_poll_id", "").strip()
        creator_identifier = request.form.get("creator_identifier", "").strip()
        creator_user_select = request.form.get("creator_user_select", "").strip()
        curl_preview = None

        def build_curl(url: str, params_dict: dict | None = None) -> str:
            if not params_dict:
                return f'curl -H "Authorization: Bearer <token>" "{url}"'
            query = urlencode(params_dict, safe=",")
            return f'curl -H "Authorization: Bearer <token>" "{url}?{query}"'

        action = request.form.get("spaces_action")
        response = None
        if action == "search_spaces":
            if not space_search_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                try:
                    max_results = int(space_search_max_results) if space_search_max_results else 100
                except ValueError:
                    max_results = 100
                max_results = min(max(max_results, 1), 100)
                state_value = space_search_state or "all"
                flash("Spaces search started.", "info")
                response = get_x_spaces_search(
                    space_search_query,
                    state=state_value,
                    max_results=max_results,
                    next_token=space_search_next_token or None,
                )
                params = {
                    "query": "<QUERY>",
                    "state": state_value,
                    "max_results": max_results,
                    "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
                    "expansions": ",".join(SPACE_EXPANSIONS),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if space_search_next_token:
                    params["next_token"] = "<NEXT_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/spaces/search", params)
        elif action == "lookup_spaces":
            cleaned = [item.strip() for item in space_ids.split(",") if item.strip()]
            if not cleaned:
                error = "Please provide at least one Space ID."
                flash(error, "warning")
            else:
                flash("Space lookup started.", "info")
                response = get_x_spaces_by_ids(cleaned)
                params = {
                    "ids": "ID1,ID2",
                    "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
                    "expansions": ",".join(SPACE_EXPANSIONS),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/spaces", params)
        elif action == "lookup_creators":
            if not creator_identifier:
                creator_identifier = creator_user_select
            identifiers = [item.strip() for item in (creator_identifier or "").split(",") if item.strip()]
            resolved_ids = []
            resolve_errors = []
            for identifier in identifiers:
                resolved_id, resolve_error = resolve_x_user_id(identifier)
                if resolve_error:
                    resolve_errors.append(resolve_error)
                elif resolved_id:
                    resolved_ids.append(resolved_id)
            if not identifiers:
                error = "Please provide at least one creator ID or username."
                flash(error, "warning")
            elif resolve_errors:
                response = None
                error = resolve_errors[0]
                flash(resolve_errors[0], "warning")
            else:
                flash("Creator lookup started.", "info")
                response = get_x_spaces_by_creator_ids(resolved_ids)
                params = {
                    "user_ids": "USER_ID1,USER_ID2",
                    "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
                    "expansions": ",".join(SPACE_EXPANSIONS),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/spaces/by/creator_ids", params)
        elif action == "space_posts":
            if not space_posts_id:
                error = "Please provide a Space ID to fetch posts."
                flash(error, "warning")
            else:
                try:
                    max_results = int(space_posts_max_results) if space_posts_max_results else 100
                except ValueError:
                    max_results = 100
                max_results = min(max(max_results, 1), 100)
                flash("Space posts lookup started.", "info")
                response = get_x_space_posts(space_posts_id, max_results=max_results)
                params = {
                    "max_results": max_results,
                    "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
                    "expansions": ",".join(_filter_fields(TWEET_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/spaces/<SPACE_ID>/tweets", params)
        elif action == "poll_space":
            if not space_poll_id:
                error = "Please provide a Space ID to poll."
                flash(error, "warning")
            else:
                flash("Space poll started.", "info")
                response = get_x_spaces_by_ids([space_poll_id])
                params = {
                    "ids": "SPACE_ID",
                    "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
                    "expansions": ",".join(SPACE_EXPANSIONS),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/spaces", params)
        else:
            error = "Please select a Spaces action to run."
            flash("Please select an action first.", "warning")

        if response is None and error is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        elif response is not None:
            def extract_problem(payload: dict) -> dict | None:
                if not isinstance(payload, dict):
                    return None
                if payload.get("type") or payload.get("title"):
                    return payload
                errors = payload.get("errors")
                if isinstance(errors, list) and errors:
                    return errors[0]
                return None

            if isinstance(response, dict):
                result = response
                problem = extract_problem(result)
                if problem and (problem.get("type") == "https://api.twitter.com/2/problems/client-forbidden" or problem.get("title") == "Client Forbidden"):
                    error = (
                        "Client Forbidden: ensure your developer App is attached to a Project "
                        "with access to Spaces endpoints."
                    )
                    flash(error, "warning")
                elif problem and problem.get("title"):
                    error = problem.get("title")
                    flash(problem.get("title"), "warning")
                elif response.get("error"):
                    error = response.get("error")
                    flash(response["error"], "warning")
                else:
                    flash("Lookup complete.", "success")
            else:
                try:
                    result = response.json()
                except ValueError:
                    result = {"raw": response.text}
                problem = extract_problem(result)
                if problem and (problem.get("type") == "https://api.twitter.com/2/problems/client-forbidden" or problem.get("title") == "Client Forbidden"):
                    error = (
                        "Client Forbidden: ensure your developer App is attached to a Project "
                        "with access to Spaces endpoints."
                    )
                    flash(error, "warning")
                elif problem and problem.get("title"):
                    error = problem.get("title")
                    flash(problem.get("title"), "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                elif error is None:
                    flash("Lookup complete.", "success")

        if action == "poll_space" and request.headers.get("X-Requested-With") == "fetch":
            detail = _build_space_detail(space_poll_id)
            if detail:
                return jsonify(detail)
            return jsonify({"error": "Space not found."}), 404

        session["x_spaces_lookup_log_id"] = session.get("x_last_api_log_id")
        session["x_spaces_lookup_error"] = error
        session["x_spaces_lookup_curl"] = curl_preview
        return redirect(url_for("x_api.spaces"))

    if isinstance(result, dict) and result.get("meta", {}).get("next_token") and not space_search_next_token:
        space_search_next_token = result["meta"]["next_token"]

    upcoming_spaces = (
        XSpace.query.filter(XSpace.state != "ended")
        .order_by(XSpace.scheduled_start.desc(), XSpace.started_at.desc())
        .limit(200)
        .all()
    )
    ended_spaces = (
        XSpace.query.filter(XSpace.state == "ended")
        .order_by(XSpace.ended_at.desc())
        .limit(200)
        .all()
    )

    def serialize_space(space: XSpace) -> dict:
        snapshots = []
        for snapshot in sorted(space.snapshots, key=lambda item: item.fetched_at or 0):
            snapshots.append(
                {
                    "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
                    "participant_count": snapshot.participant_count,
                }
            )
        return {
            "id": space.id,
            "title": space.title,
            "state": space.state,
            "scheduled_start": space.scheduled_start,
            "started_at": space.started_at,
            "ended_at": space.ended_at,
            "creator_id": str(space.creator_id) if space.creator_id is not None else None,
            "participant_count": space.participant_count,
            "creator_user": space.creator,
            "raw_space_data": space.raw_space_data,
            "snapshots": snapshots,
        }

    upcoming_spaces_payload = [serialize_space(space) for space in upcoming_spaces]
    ended_spaces_payload = [serialize_space(space) for space in ended_spaces]

    space_snapshots_by_id = {}
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        creator_ids = []
        space_ids = []
        for item in result["data"]:
            if not isinstance(item, dict):
                continue
            creator_id = item.get("creator_id")
            try:
                if creator_id:
                    creator_ids.append(int(creator_id))
            except (TypeError, ValueError):
                continue
            space_id = item.get("id")
            if space_id:
                space_ids.append(str(space_id))
        if creator_ids:
            for user in XUser.query.filter(XUser.id.in_(creator_ids)).all():
                known_users_by_id[str(user.id)] = user
        if space_ids:
            for space in XSpace.query.filter(XSpace.id.in_(space_ids)).all():
                space_snapshots_by_id[space.id] = [
                    {
                        "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
                        "participant_count": snapshot.participant_count,
                    }
                    for snapshot in sorted(space.snapshots, key=lambda item: item.fetched_at or 0)
                ]

    return render_template(
        "x_api/spaces.html",
        space_search_query=space_search_query,
        space_search_state=space_search_state,
        space_search_max_results=space_search_max_results,
        space_search_next_token=space_search_next_token,
        space_ids=space_ids,
        space_posts_id=space_posts_id,
        space_posts_max_results=space_posts_max_results,
        space_poll_id=space_poll_id,
        creator_identifier=creator_identifier,
        creator_user_select=creator_user_select,
        result=result,
        error=error,
        curl_preview=curl_preview,
        known_users_by_id=known_users_by_id,
        existing_users=existing_users,
        upcoming_spaces=upcoming_spaces_payload,
        ended_spaces=ended_spaces_payload,
        space_snapshots_by_id=space_snapshots_by_id,
    )


def _build_space_detail(space_id: str) -> dict | None:
    space = XSpace.query.filter_by(id=space_id).first()
    if not space:
        return None
    raw = space.raw_space_data or {}
    snapshots = [
        {
            "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
            "participant_count": snapshot.participant_count,
        }
        for snapshot in sorted(space.snapshots, key=lambda item: item.fetched_at or 0)
    ]
    ids = set()
    for key in ("creator_id",):
        if raw.get(key):
            ids.add(str(raw[key]))
    for key in ("host_ids", "speaker_ids", "invited_user_ids"):
        for value in raw.get(key, []) or []:
            if value:
                ids.add(str(value))
    users = {}
    if ids:
        numeric_ids = []
        for value in ids:
            try:
                numeric_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        for user in XUser.query.filter(XUser.id.in_(numeric_ids)).all():
            users[str(user.id)] = {
                "id": str(user.id),
                "username": user.username,
                "name": user.name,
                "profile_image_url": user.profile_image_url,
            }
    return {
        "space_id": space.id,
        "space": raw,
        "snapshots": snapshots,
        "users": users,
    }


@bp.route("/spaces/<space_id>/detail", methods=["GET"])
@login_required
def space_detail(space_id: str):
    detail = _build_space_detail(space_id)
    if not detail:
        return jsonify({"error": "Space not found."}), 404
    return jsonify(detail)


@bp.route("/spaces/<space_id>/refresh-users", methods=["POST"])
@login_required
def space_refresh_users(space_id: str):
    space = XSpace.query.filter_by(id=space_id).first()
    if not space:
        return jsonify({"error": "Space not found."}), 404
    raw = space.raw_space_data or {}
    ids = set()
    if raw.get("creator_id"):
        ids.add(str(raw["creator_id"]))
    for key in ("host_ids", "speaker_ids", "invited_user_ids"):
        for value in raw.get(key, []) or []:
            if value:
                ids.add(str(value))
    if ids:
        get_x_users_by_ids_with_app_token(list(ids))
    detail = _build_space_detail(space_id)
    if not detail:
        return jsonify({"error": "Space not found."}), 404
    return jsonify(detail)


@bp.route("/lists", methods=["GET", "POST"])
@login_required
def lists():
    list_id = ""
    followed_user_identifier = ""
    followed_user_select = ""
    followed_max_results = ""
    followed_pagination_token = ""
    owned_user_identifier = ""
    owned_user_select = ""
    owned_max_results = ""
    owned_pagination_token = ""
    membership_user_identifier = ""
    membership_user_select = ""
    membership_max_results = ""
    membership_pagination_token = ""
    list_tweets_id = ""
    list_tweets_max_results = ""
    list_tweets_pagination_token = ""
    list_followers_id = ""
    list_followers_max_results = ""
    list_followers_pagination_token = ""
    list_members_id = ""
    list_members_max_results = ""
    list_members_pagination_token = ""
    list_create_name = ""
    list_create_description = ""
    list_create_private = False
    list_update_id = ""
    list_update_name = ""
    list_update_description = ""
    list_update_private = ""
    list_delete_id = ""
    follow_list_id = ""
    unfollow_list_id = ""
    add_member_list_id = ""
    add_member_user_id = ""
    add_member_user_select = ""
    remove_member_list_id = ""
    remove_member_user_id = ""
    remove_member_user_select = ""
    pinned_user_identifier = ""
    pinned_user_select = ""
    pin_list_id = ""
    unpin_list_id = ""
    result = None
    error = session.get("x_lists_lookup_error")
    known_limit = session.get("x_lists_known_limit")
    curl_preview = session.get("x_lists_lookup_curl")
    log_id = session.get("x_lists_lookup_log_id")
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
        known_limit = None
        list_id = request.form.get("list_id", "").strip()
        followed_user_identifier = request.form.get("followed_user_identifier", "").strip()
        followed_user_select = request.form.get("followed_user_select", "").strip()
        followed_max_results = request.form.get("followed_max_results", "").strip()
        followed_pagination_token = request.form.get("followed_pagination_token", "").strip()
        owned_user_identifier = request.form.get("owned_user_identifier", "").strip()
        owned_user_select = request.form.get("owned_user_select", "").strip()
        owned_max_results = request.form.get("owned_max_results", "").strip()
        owned_pagination_token = request.form.get("owned_pagination_token", "").strip()
        membership_user_identifier = request.form.get("membership_user_identifier", "").strip()
        membership_user_select = request.form.get("membership_user_select", "").strip()
        membership_max_results = request.form.get("membership_max_results", "").strip()
        membership_pagination_token = request.form.get("membership_pagination_token", "").strip()
        list_tweets_id = request.form.get("list_tweets_id", "").strip()
        list_tweets_max_results = request.form.get("list_tweets_max_results", "").strip()
        list_tweets_pagination_token = request.form.get("list_tweets_pagination_token", "").strip()
        list_followers_id = request.form.get("list_followers_id", "").strip()
        list_followers_max_results = request.form.get("list_followers_max_results", "").strip()
        list_followers_pagination_token = request.form.get("list_followers_pagination_token", "").strip()
        list_members_id = request.form.get("list_members_id", "").strip()
        list_members_max_results = request.form.get("list_members_max_results", "").strip()
        list_members_pagination_token = request.form.get("list_members_pagination_token", "").strip()
        list_create_name = request.form.get("list_create_name", "").strip()
        list_create_description = request.form.get("list_create_description", "").strip()
        list_create_private = request.form.get("list_create_private") == "on"
        list_update_id = request.form.get("list_update_id", "").strip()
        list_update_name = request.form.get("list_update_name", "").strip()
        list_update_description = request.form.get("list_update_description", "").strip()
        list_update_private = request.form.get("list_update_private", "").strip()
        list_delete_id = request.form.get("list_delete_id", "").strip()
        follow_list_id = request.form.get("follow_list_id", "").strip()
        unfollow_list_id = request.form.get("unfollow_list_id", "").strip()
        add_member_list_id = request.form.get("add_member_list_id", "").strip()
        add_member_user_id = request.form.get("add_member_user_id", "").strip()
        add_member_user_select = request.form.get("add_member_user_select", "").strip()
        remove_member_list_id = request.form.get("remove_member_list_id", "").strip()
        remove_member_user_id = request.form.get("remove_member_user_id", "").strip()
        remove_member_user_select = request.form.get("remove_member_user_select", "").strip()
        pinned_user_identifier = request.form.get("pinned_user_identifier", "").strip()
        pinned_user_select = request.form.get("pinned_user_select", "").strip()
        pin_list_id = request.form.get("pin_list_id", "").strip()
        unpin_list_id = request.form.get("unpin_list_id", "").strip()
        curl_preview = None

        def build_curl(url: str, params_dict: dict | None = None, method: str = "GET", payload: dict | None = None) -> str:
            query = urlencode(params_dict or {}, safe=",")
            full_url = f"{url}?{query}" if query else url
            if method == "GET":
                return f'curl -H "Authorization: Bearer <token>" "{full_url}"'
            base = f'curl -X {method} -H "Authorization: Bearer <token>"'
            if payload is not None:
                base += ' -H "Content-Type: application/json"'
            base += f' "{full_url}"'
            if payload is not None:
                base += f" -d '{json.dumps(payload)}'"
            return base

        def parse_max_results(raw_value: str, default: int = 100) -> int:
            try:
                value = int(raw_value) if raw_value else default
            except ValueError:
                value = default
            return min(max(value, 1), 100)

        action = request.form.get("lists_action")
        if action == "list_by_id":
            if not list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                flash("List lookup started.", "info")
                response = get_x_list_by_id(list_id)
                params = {
                    "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
                    "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/lists/<LIST_ID>", params)
        elif action == "followed_lists":
            if not followed_user_identifier:
                followed_user_identifier = followed_user_select or session.get("active_x_user_id", "")
                if followed_user_identifier:
                    flash("Using your active X account for followed lists.", "info")
            resolved_id, resolve_error = resolve_x_user_id(followed_user_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                max_results = parse_max_results(followed_max_results)
                flash("Followed lists lookup started.", "info")
                response = get_x_user_followed_lists(
                    resolved_id,
                    max_results=max_results,
                    pagination_token=followed_pagination_token or None,
                )
                params = {
                    "max_results": max_results,
                    "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
                    "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if followed_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/users/<USER_ID>/followed_lists", params)
        elif action == "owned_lists":
            if not owned_user_identifier:
                owned_user_identifier = owned_user_select or session.get("active_x_user_id", "")
                if owned_user_identifier:
                    flash("Using your active X account for owned lists.", "info")
            resolved_id, resolve_error = resolve_x_user_id(owned_user_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                max_results = parse_max_results(owned_max_results)
                flash("Owned lists lookup started.", "info")
                response = get_x_user_owned_lists(
                    resolved_id,
                    max_results=max_results,
                    pagination_token=owned_pagination_token or None,
                )
                params = {
                    "max_results": max_results,
                    "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
                    "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if owned_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/users/<USER_ID>/owned_lists", params)
        elif action == "list_memberships":
            if not membership_user_identifier:
                membership_user_identifier = membership_user_select or session.get("active_x_user_id", "")
                if membership_user_identifier:
                    flash("Using your active X account for list memberships.", "info")
            resolved_id, resolve_error = resolve_x_user_id(membership_user_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                max_results = parse_max_results(membership_max_results)
                flash("List memberships lookup started.", "info")
                response = get_x_user_list_memberships(
                    resolved_id,
                    max_results=max_results,
                    pagination_token=membership_pagination_token or None,
                )
                params = {
                    "max_results": max_results,
                    "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
                    "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if membership_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/users/<USER_ID>/list_memberships", params)
        elif action == "list_tweets":
            if not list_tweets_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                max_results = parse_max_results(list_tweets_max_results)
                flash("List posts lookup started.", "info")
                response = get_x_list_tweets(
                    list_tweets_id,
                    max_results=max_results,
                    pagination_token=list_tweets_pagination_token or None,
                )
                params = {
                    "max_results": max_results,
                    "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
                    "expansions": ",".join(_filter_fields(TWEET_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if list_tweets_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/lists/<LIST_ID>/tweets", params)
        elif action == "list_followers":
            if not list_followers_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                max_results = parse_max_results(list_followers_max_results)
                flash("List followers lookup started.", "info")
                response = get_x_list_followers(
                    list_followers_id,
                    max_results=max_results,
                    pagination_token=list_followers_pagination_token or None,
                )
                params = {
                    "max_results": max_results,
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if list_followers_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/lists/<LIST_ID>/followers", params)
        elif action == "list_members":
            if not list_members_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                max_results = parse_max_results(list_members_max_results)
                flash("List members lookup started.", "info")
                response = get_x_list_members(
                    list_members_id,
                    max_results=max_results,
                    pagination_token=list_members_pagination_token or None,
                )
                params = {
                    "max_results": max_results,
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                if list_members_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/lists/<LIST_ID>/members", params)
        elif action == "create_list":
            if not list_create_name:
                response = None
                error = "Please provide a list name."
                flash("Please provide a list name first.", "warning")
            else:
                flash("Create list started.", "info")
                response = create_x_list(
                    list_create_name,
                    description=list_create_description or None,
                    private=list_create_private,
                )
                payload = {"name": "<NAME>", "description": "<DESCRIPTION>", "private": list_create_private}
                if not list_create_description:
                    payload.pop("description")
                curl_preview = build_curl("https://api.x.com/2/lists", method="POST", payload=payload)
        elif action == "update_list":
            if not list_update_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                private_value = None
                if list_update_private == "true":
                    private_value = True
                elif list_update_private == "false":
                    private_value = False
                if not any([list_update_name, list_update_description != "", list_update_private in {"true", "false"}]):
                    response = None
                    error = "Please provide at least one field to update."
                    flash("Please provide at least one field to update.", "warning")
                else:
                    flash("Update list started.", "info")
                    response = update_x_list(
                        list_update_id,
                        name=list_update_name or None,
                        description=list_update_description if list_update_description != "" else None,
                        private=private_value,
                    )
                    payload = {}
                    if list_update_name:
                        payload["name"] = "<NAME>"
                    if list_update_description != "":
                        payload["description"] = "<DESCRIPTION>"
                    if list_update_private in {"true", "false"}:
                        payload["private"] = list_update_private == "true"
                    curl_preview = build_curl("https://api.x.com/2/lists/<LIST_ID>", method="PUT", payload=payload or {"name": "<NAME>"})
        elif action == "delete_list":
            if not list_delete_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                flash("Delete list started.", "info")
                response = delete_x_list(list_delete_id)
                curl_preview = build_curl("https://api.x.com/2/lists/<LIST_ID>", method="DELETE")
        elif action == "follow_list":
            if not follow_list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                flash("Follow list started.", "info")
                response = follow_x_list(follow_list_id)
                curl_preview = build_curl(
                    "https://api.x.com/2/users/<ME>/followed_lists",
                    method="POST",
                    payload={"list_id": "<LIST_ID>"},
                )
        elif action == "unfollow_list":
            if not unfollow_list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                flash("Unfollow list started.", "info")
                response = unfollow_x_list(unfollow_list_id)
                curl_preview = build_curl("https://api.x.com/2/users/<ME>/followed_lists/<LIST_ID>", method="DELETE")
        elif action == "add_member":
            if not add_member_list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                if not add_member_user_id:
                    add_member_user_id = add_member_user_select
                resolved_id, resolve_error = resolve_x_user_id(add_member_user_id)
                if resolve_error:
                    response = None
                    error = resolve_error
                    flash(resolve_error, "warning")
                else:
                    flash("Add member started.", "info")
                    response = add_x_list_member(add_member_list_id, resolved_id)
                    curl_preview = build_curl(
                        "https://api.x.com/2/lists/<LIST_ID>/members",
                        method="POST",
                        payload={"user_id": "<USER_ID>"},
                    )
        elif action == "remove_member":
            if not remove_member_list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                if not remove_member_user_id:
                    remove_member_user_id = remove_member_user_select
                resolved_id, resolve_error = resolve_x_user_id(remove_member_user_id)
                if resolve_error:
                    response = None
                    error = resolve_error
                    flash(resolve_error, "warning")
                else:
                    flash("Remove member started.", "info")
                    response = remove_x_list_member(remove_member_list_id, resolved_id)
                    curl_preview = build_curl(
                        "https://api.x.com/2/lists/<LIST_ID>/members/<USER_ID>",
                        method="DELETE",
                    )
        elif action == "pinned_lists":
            if not pinned_user_identifier:
                pinned_user_identifier = pinned_user_select or session.get("active_x_user_id", "")
                if pinned_user_identifier:
                    flash("Using your active X account for pinned lists.", "info")
            resolved_id, resolve_error = resolve_x_user_id(pinned_user_identifier)
            if resolve_error:
                response = None
                error = resolve_error
                flash(resolve_error, "warning")
            else:
                flash("Pinned lists lookup started.", "info")
                response = get_x_user_pinned_lists(resolved_id)
                params = {
                    "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
                    "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
                    "user.fields": ",".join(_filter_fields(USER_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/users/<USER_ID>/pinned_lists", params)
        elif action == "pin_list":
            if not pin_list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                flash("Pin list started.", "info")
                response = pin_x_list(pin_list_id)
                curl_preview = build_curl(
                    "https://api.x.com/2/users/<ME>/pinned_lists",
                    method="POST",
                    payload={"list_id": "<LIST_ID>"},
                )
        elif action == "unpin_list":
            if not unpin_list_id:
                response = None
                error = "Please provide a list ID."
                flash("Please provide a list ID first.", "warning")
            else:
                flash("Unpin list started.", "info")
                response = unpin_x_list(unpin_list_id)
                curl_preview = build_curl("https://api.x.com/2/users/<ME>/pinned_lists/<LIST_ID>", method="DELETE")
        else:
            response = None
            error = "Please select a list action to run."
            flash("Please select an action first.", "warning")

        def extract_problem(payload: dict) -> dict | None:
            if not isinstance(payload, dict):
                return None
            if payload.get("type") or payload.get("title"):
                return payload
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                return errors[0]
            return None

        if response is None and error is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        elif response is not None:
            if isinstance(response, dict):
                result = response
                problem = extract_problem(result)
                if problem and (
                    problem.get("type") == "https://api.twitter.com/2/problems/client-forbidden"
                    or problem.get("title") == "Client Forbidden"
                ):
                    known_limit = (
                        "X returned Client Forbidden for this endpoint. "
                        "Your developer app needs to be attached to a Project with the required API access level."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.get("error"):
                    flash(response["error"], "warning")
                else:
                    flash("Lookup complete.", "success")
            else:
                try:
                    result = response.json()
                except ValueError:
                    result = {"raw": response.text}
                problem = extract_problem(result)
                if problem and (
                    problem.get("type") == "https://api.twitter.com/2/problems/client-forbidden"
                    or problem.get("title") == "Client Forbidden"
                ):
                    known_limit = (
                        "X returned Client Forbidden for this endpoint. "
                        "Your developer app needs to be attached to a Project with the required API access level."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        session["x_lists_lookup_log_id"] = session.get("x_last_api_log_id")
        session["x_lists_lookup_error"] = error
        session["x_lists_lookup_curl"] = curl_preview
        session["x_lists_known_limit"] = known_limit
        return redirect(url_for("x_api.lists"))

    return render_template(
        "x_api/lists.html",
        list_id=list_id,
        followed_user_identifier=followed_user_identifier,
        followed_user_select=followed_user_select,
        followed_max_results=followed_max_results,
        followed_pagination_token=followed_pagination_token,
        owned_user_identifier=owned_user_identifier,
        owned_user_select=owned_user_select,
        owned_max_results=owned_max_results,
        owned_pagination_token=owned_pagination_token,
        membership_user_identifier=membership_user_identifier,
        membership_user_select=membership_user_select,
        membership_max_results=membership_max_results,
        membership_pagination_token=membership_pagination_token,
        list_tweets_id=list_tweets_id,
        list_tweets_max_results=list_tweets_max_results,
        list_tweets_pagination_token=list_tweets_pagination_token,
        list_followers_id=list_followers_id,
        list_followers_max_results=list_followers_max_results,
        list_followers_pagination_token=list_followers_pagination_token,
        list_members_id=list_members_id,
        list_members_max_results=list_members_max_results,
        list_members_pagination_token=list_members_pagination_token,
        list_create_name=list_create_name,
        list_create_description=list_create_description,
        list_create_private=list_create_private,
        list_update_id=list_update_id,
        list_update_name=list_update_name,
        list_update_description=list_update_description,
        list_update_private=list_update_private,
        list_delete_id=list_delete_id,
        follow_list_id=follow_list_id,
        unfollow_list_id=unfollow_list_id,
        add_member_list_id=add_member_list_id,
        add_member_user_id=add_member_user_id,
        add_member_user_select=add_member_user_select,
        remove_member_list_id=remove_member_list_id,
        remove_member_user_id=remove_member_user_id,
        remove_member_user_select=remove_member_user_select,
        pinned_user_identifier=pinned_user_identifier,
        pinned_user_select=pinned_user_select,
        pin_list_id=pin_list_id,
        unpin_list_id=unpin_list_id,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        token_scope=token_scope,
        existing_users=XUser.query.order_by(XUser.username.asc()).limit(200).all(),
    )
