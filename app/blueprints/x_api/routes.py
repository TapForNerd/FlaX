import io
from typing import Any
from urllib.parse import urlencode

import json

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
import requests

from app.blueprints.auth.decorators import login_required
from app.blueprints.auth.token_helpers import call_x_api_with_refresh
from app.blueprints.x_api.commands import x_api_cli
from app.blueprints.x_api.helpers import (
    EXPANSIONS,
    COMMUNITY_FIELDS,
    ACTIVITY_EVENT_TYPES,
    MEDIA_FIELDS,
    POLL_FIELDS,
    PLACE_FIELDS,
    SEARCH_COUNT_FIELDS,
    LIST_EXPANSIONS,
    LIST_FIELDS,
    NEWS_FIELDS,
    PERSONALIZED_TREND_FIELDS,
    IMAGE_FORMATS,
    SPACE_EXPANSIONS,
    SPACE_FIELDS,
    TWEET_EXPANSIONS,
    TWEET_FIELDS,
    TREND_FIELDS,
    USAGE_FIELDS,
    USER_FIELDS,
    _filter_fields,
    _process_image_bytes,
    add_x_list_member,
    create_x_list,
    create_x_activity_subscription,
    create_x_post,
    delete_x_activity_subscription,
    delete_x_post,
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
    get_x_personalized_trends,
    get_x_trends_by_woeid,
    get_x_news_by_id,
    get_x_home_timeline,
    get_x_activity_subscriptions,
    get_x_media_upload_status,
    get_x_post_by_id,
    get_x_posts_by_ids,
    get_x_posts_counts_all,
    get_x_posts_counts_recent,
    get_x_quote_tweets,
    get_x_reposts_of_me,
    get_x_user_mentions,
    get_x_user_posts,
    initialize_x_media_upload,
    append_x_media_upload,
    finalize_x_media_upload,
    upload_x_media_one_shot,
    get_x_usage_tweets,
    search_x_news,
    like_x_post,
    mute_x_user,
    pin_x_list,
    remove_x_list_member,
    resolve_x_user_id,
    resolve_x_post_id,
    search_x_communities,
    search_x_posts_all,
    search_x_posts_recent,
    unmute_x_user,
    unfollow_x_list,
    unlike_x_post,
    unpin_x_list,
    unrepost_x_post,
    update_x_list,
    repost_x_post,
    update_x_activity_subscription,
)
from app.extensions import db
from app.models import ApiRequestLog, UserOAuthToken, XMediaUpload, XNewsStorySnapshot, XPost, XSpace, XTrendSnapshot, XUsageSnapshot, XUser
from app.models import UserLinkedAccount
from sqlalchemy import String, or_, cast

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


@bp.route("/activity", methods=["GET", "POST"])
@login_required
def activity():
    event_type = ""
    event_type_custom = ""
    filter_type = "user_id"
    filter_user_identifier = ""
    filter_user_select = ""
    filter_keyword = ""
    tag = ""
    webhook_id = ""
    update_subscription_id = ""
    update_tag = ""
    update_webhook_id = ""
    delete_subscription_id = ""
    result = None
    error = session.get("x_activity_lookup_error")
    known_limit = session.get("x_activity_known_limit")
    curl_preview = session.get("x_activity_lookup_curl")
    log_id = session.get("x_activity_lookup_log_id")

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
        event_type = request.form.get("event_type", "").strip()
        event_type_custom = request.form.get("event_type_custom", "").strip()
        filter_type = request.form.get("filter_type", "user_id").strip() or "user_id"
        filter_user_identifier = request.form.get("filter_user_identifier", "").strip()
        filter_user_select = request.form.get("filter_user_select", "").strip()
        filter_keyword = request.form.get("filter_keyword", "").strip()
        tag = request.form.get("tag", "").strip()
        webhook_id = request.form.get("webhook_id", "").strip()
        update_subscription_id = request.form.get("update_subscription_id", "").strip()
        update_tag = request.form.get("update_tag", "").strip()
        update_webhook_id = request.form.get("update_webhook_id", "").strip()
        delete_subscription_id = request.form.get("delete_subscription_id", "").strip()
        curl_preview = None

        def build_curl(
            url: str,
            method: str = "GET",
            params_dict: dict | None = None,
            payload: dict | None = None,
        ) -> str:
            parts = ['curl -H "Authorization: Bearer <token>"']
            if method != "GET":
                parts.append(f"-X {method}")
            if payload is not None:
                parts.append(f"-d '{json.dumps(payload, indent=2)}'")
            if params_dict:
                query = urlencode(params_dict, safe=",")
                return " ".join(parts + [f'"{url}?{query}"'])
            return " ".join(parts + [f'"{url}"'])

        action = request.form.get("activity_action")
        response = None
        if action == "create_subscription":
            selected_event_type = event_type_custom or event_type
            if not selected_event_type:
                error = "Please provide an event type."
                flash(error, "warning")
            else:
                filter_payload = None
                if filter_type == "keyword":
                    if not filter_keyword:
                        error = "Please provide a keyword filter."
                        flash(error, "warning")
                    else:
                        filter_payload = {"keyword": filter_keyword}
                else:
                    identifier = filter_user_select or filter_user_identifier
                    if not identifier:
                        error = "Please provide a user ID or username."
                        flash(error, "warning")
                    else:
                        resolved_user_id, resolve_error = resolve_x_user_id(identifier)
                        if resolve_error:
                            error = resolve_error
                            flash(resolve_error, "warning")
                        else:
                            filter_payload = {"user_id": resolved_user_id}

                if filter_payload:
                    flash("Subscription create started.", "info")
                    response = create_x_activity_subscription(
                        selected_event_type,
                        filter_payload,
                        tag=tag or None,
                        webhook_id=webhook_id or None,
                    )
                    curl_payload = {
                        "event_type": "<EVENT_TYPE>",
                        "filter": {"keyword": "<KEYWORD>"} if filter_type == "keyword" else {"user_id": "<USER_ID>"},
                    }
                    if tag:
                        curl_payload["tag"] = "<TAG>"
                    if webhook_id:
                        curl_payload["webhook_id"] = "<WEBHOOK_ID>"
                    curl_preview = build_curl(
                        "https://api.x.com/2/activity/subscriptions",
                        method="POST",
                        payload=curl_payload,
                    )
        elif action == "list_subscriptions":
            flash("Subscription list started.", "info")
            response = get_x_activity_subscriptions()
            curl_preview = build_curl("https://api.x.com/2/activity/subscriptions")
        elif action == "update_subscription":
            if not update_subscription_id:
                error = "Please provide a subscription ID to update."
                flash(error, "warning")
            else:
                update_payload = {}
                if update_tag:
                    update_payload["tag"] = update_tag
                if update_webhook_id:
                    update_payload["webhook_id"] = update_webhook_id
                if not update_payload:
                    error = "Provide at least one value (tag or webhook ID) to update."
                    flash(error, "warning")
                else:
                    flash("Subscription update started.", "info")
                    response = update_x_activity_subscription(
                        update_subscription_id,
                        tag=update_tag or None,
                        webhook_id=update_webhook_id or None,
                    )
                    curl_payload = {}
                    if update_tag:
                        curl_payload["tag"] = "<TAG>"
                    if update_webhook_id:
                        curl_payload["webhook_id"] = "<WEBHOOK_ID>"
                    curl_preview = build_curl(
                        "https://api.x.com/2/activity/subscriptions/<SUBSCRIPTION_ID>",
                        method="PUT",
                        payload=curl_payload,
                    )
        elif action == "delete_subscription":
            if not delete_subscription_id:
                error = "Please provide a subscription ID to delete."
                flash(error, "warning")
            else:
                flash("Subscription delete started.", "info")
                response = delete_x_activity_subscription(delete_subscription_id)
                curl_preview = build_curl(
                    "https://api.x.com/2/activity/subscriptions/<SUBSCRIPTION_ID>",
                    method="DELETE",
                )
        else:
            response = None
            error = "Please select an activity action to run."
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
                if response.get("error"):
                    error = response["error"]
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
                        "Your developer app may need elevated access to use X Activity API."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        log_id = session.get("x_last_api_log_id") if response is not None else None
        if isinstance(response, dict) and response.get("error") and not log_id:
            log_id = None
        session["x_activity_lookup_log_id"] = log_id
        session["x_activity_lookup_error"] = error
        session["x_activity_lookup_curl"] = curl_preview
        session["x_activity_known_limit"] = known_limit
        return redirect(url_for("x_api.activity"))

    return render_template(
        "x_api/activity.html",
        event_type=event_type,
        event_type_custom=event_type_custom,
        filter_type=filter_type,
        filter_user_identifier=filter_user_identifier,
        filter_user_select=filter_user_select,
        filter_keyword=filter_keyword,
        tag=tag,
        webhook_id=webhook_id,
        update_subscription_id=update_subscription_id,
        update_tag=update_tag,
        update_webhook_id=update_webhook_id,
        delete_subscription_id=delete_subscription_id,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        event_types=ACTIVITY_EVENT_TYPES,
        existing_users=XUser.query.order_by(XUser.username.asc()).limit(200).all(),
    )


@bp.route("/posts", methods=["GET", "POST"])
@login_required
def posts():
    post_text = ""
    post_card_uri = ""
    post_direct_message_deep_link = ""
    post_quote_tweet_id = ""
    post_community_id = ""
    post_geo_place_id = ""
    post_reply_settings = ""
    post_for_super_followers_only = False
    post_nullcast = False
    post_share_with_followers = False
    post_media_ids = ""
    post_media_tagged_user_ids = ""
    post_media_select = []
    post_poll_options = ""
    post_poll_duration = ""
    post_poll_reply_settings = ""
    post_reply_to_id = ""
    post_reply_auto_metadata = False
    post_reply_exclude_user_ids = ""
    post_edit_previous_id = ""
    post_schedule_time = ""
    delete_post_id = ""
    repost_post_id = ""
    lookup_post_id = ""
    lookup_post_ids = ""
    quote_post_id = ""
    quote_max_results = ""
    quote_pagination_token = ""
    quote_exclude_replies = False
    quote_exclude_retweets = False
    search_recent_query = ""
    search_recent_start_time = ""
    search_recent_end_time = ""
    search_recent_since_id = ""
    search_recent_until_id = ""
    search_recent_max_results = ""
    search_recent_next_token = ""
    search_recent_pagination_token = ""
    search_recent_sort_order = ""
    search_all_query = ""
    search_all_start_time = ""
    search_all_end_time = ""
    search_all_since_id = ""
    search_all_until_id = ""
    search_all_max_results = ""
    search_all_next_token = ""
    search_all_pagination_token = ""
    search_all_sort_order = ""
    counts_recent_query = ""
    counts_recent_start_time = ""
    counts_recent_end_time = ""
    counts_recent_since_id = ""
    counts_recent_until_id = ""
    counts_recent_granularity = ""
    counts_recent_next_token = ""
    counts_recent_pagination_token = ""
    counts_all_query = ""
    counts_all_start_time = ""
    counts_all_end_time = ""
    counts_all_since_id = ""
    counts_all_until_id = ""
    counts_all_granularity = ""
    counts_all_next_token = ""
    counts_all_pagination_token = ""
    timeline_user_identifier = ""
    timeline_user_select = ""
    timeline_max_results = ""
    timeline_pagination_token = ""
    timeline_since_id = ""
    timeline_until_id = ""
    timeline_start_time = ""
    timeline_end_time = ""
    timeline_exclude_replies = False
    timeline_exclude_retweets = False
    mentions_user_identifier = ""
    mentions_user_select = ""
    mentions_max_results = ""
    mentions_pagination_token = ""
    mentions_since_id = ""
    mentions_until_id = ""
    mentions_start_time = ""
    mentions_end_time = ""
    home_max_results = ""
    home_pagination_token = ""
    home_since_id = ""
    home_until_id = ""
    home_start_time = ""
    home_end_time = ""
    home_exclude_replies = False
    home_exclude_retweets = False
    reposts_max_results = ""
    reposts_pagination_token = ""
    result = None
    error = session.get("x_posts_lookup_error")
    known_limit = session.get("x_posts_known_limit")
    curl_preview = session.get("x_posts_lookup_curl")
    log_id = session.get("x_posts_lookup_log_id")

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
        post_text = request.form.get("post_text", "").strip()
        post_card_uri = request.form.get("post_card_uri", "").strip()
        post_direct_message_deep_link = request.form.get("post_direct_message_deep_link", "").strip()
        post_quote_tweet_id = request.form.get("post_quote_tweet_id", "").strip()
        post_community_id = request.form.get("post_community_id", "").strip()
        post_geo_place_id = request.form.get("post_geo_place_id", "").strip()
        post_reply_settings = request.form.get("post_reply_settings", "").strip()
        post_for_super_followers_only = request.form.get("post_for_super_followers_only") == "on"
        post_nullcast = request.form.get("post_nullcast") == "on"
        post_share_with_followers = request.form.get("post_share_with_followers") == "on"
        post_media_ids = request.form.get("post_media_ids", "").strip()
        post_media_tagged_user_ids = request.form.get("post_media_tagged_user_ids", "").strip()
        post_media_select = request.form.getlist("post_media_select")
        post_poll_options = request.form.get("post_poll_options", "").strip()
        post_poll_duration = request.form.get("post_poll_duration", "").strip()
        post_poll_reply_settings = request.form.get("post_poll_reply_settings", "").strip()
        post_reply_to_id = request.form.get("post_reply_to_id", "").strip()
        post_reply_auto_metadata = request.form.get("post_reply_auto_metadata") == "on"
        post_reply_exclude_user_ids = request.form.get("post_reply_exclude_user_ids", "").strip()
        post_edit_previous_id = request.form.get("post_edit_previous_id", "").strip()
        post_schedule_time = request.form.get("post_schedule_time", "").strip()
        delete_post_id = request.form.get("delete_post_id", "").strip()
        repost_post_id = request.form.get("repost_post_id", "").strip()
        lookup_post_id = request.form.get("lookup_post_id", "").strip()
        lookup_post_ids = request.form.get("lookup_post_ids", "").strip()
        quote_post_id = request.form.get("quote_post_id", "").strip()
        quote_max_results = request.form.get("quote_max_results", "").strip()
        quote_pagination_token = request.form.get("quote_pagination_token", "").strip()
        quote_exclude_replies = request.form.get("quote_exclude_replies") == "on"
        quote_exclude_retweets = request.form.get("quote_exclude_retweets") == "on"
        search_recent_query = request.form.get("search_recent_query", "").strip()
        search_recent_start_time = request.form.get("search_recent_start_time", "").strip()
        search_recent_end_time = request.form.get("search_recent_end_time", "").strip()
        search_recent_since_id = request.form.get("search_recent_since_id", "").strip()
        search_recent_until_id = request.form.get("search_recent_until_id", "").strip()
        search_recent_max_results = request.form.get("search_recent_max_results", "").strip()
        search_recent_next_token = request.form.get("search_recent_next_token", "").strip()
        search_recent_pagination_token = request.form.get("search_recent_pagination_token", "").strip()
        search_recent_sort_order = request.form.get("search_recent_sort_order", "").strip()
        search_all_query = request.form.get("search_all_query", "").strip()
        search_all_start_time = request.form.get("search_all_start_time", "").strip()
        search_all_end_time = request.form.get("search_all_end_time", "").strip()
        search_all_since_id = request.form.get("search_all_since_id", "").strip()
        search_all_until_id = request.form.get("search_all_until_id", "").strip()
        search_all_max_results = request.form.get("search_all_max_results", "").strip()
        search_all_next_token = request.form.get("search_all_next_token", "").strip()
        search_all_pagination_token = request.form.get("search_all_pagination_token", "").strip()
        search_all_sort_order = request.form.get("search_all_sort_order", "").strip()
        counts_recent_query = request.form.get("counts_recent_query", "").strip()
        counts_recent_start_time = request.form.get("counts_recent_start_time", "").strip()
        counts_recent_end_time = request.form.get("counts_recent_end_time", "").strip()
        counts_recent_since_id = request.form.get("counts_recent_since_id", "").strip()
        counts_recent_until_id = request.form.get("counts_recent_until_id", "").strip()
        counts_recent_granularity = request.form.get("counts_recent_granularity", "").strip()
        counts_recent_next_token = request.form.get("counts_recent_next_token", "").strip()
        counts_recent_pagination_token = request.form.get("counts_recent_pagination_token", "").strip()
        counts_all_query = request.form.get("counts_all_query", "").strip()
        counts_all_start_time = request.form.get("counts_all_start_time", "").strip()
        counts_all_end_time = request.form.get("counts_all_end_time", "").strip()
        counts_all_since_id = request.form.get("counts_all_since_id", "").strip()
        counts_all_until_id = request.form.get("counts_all_until_id", "").strip()
        counts_all_granularity = request.form.get("counts_all_granularity", "").strip()
        counts_all_next_token = request.form.get("counts_all_next_token", "").strip()
        counts_all_pagination_token = request.form.get("counts_all_pagination_token", "").strip()
        timeline_user_identifier = request.form.get("timeline_user_identifier", "").strip()
        timeline_user_select = request.form.get("timeline_user_select", "").strip()
        timeline_max_results = request.form.get("timeline_max_results", "").strip()
        timeline_pagination_token = request.form.get("timeline_pagination_token", "").strip()
        timeline_since_id = request.form.get("timeline_since_id", "").strip()
        timeline_until_id = request.form.get("timeline_until_id", "").strip()
        timeline_start_time = request.form.get("timeline_start_time", "").strip()
        timeline_end_time = request.form.get("timeline_end_time", "").strip()
        timeline_exclude_replies = request.form.get("timeline_exclude_replies") == "on"
        timeline_exclude_retweets = request.form.get("timeline_exclude_retweets") == "on"
        mentions_user_identifier = request.form.get("mentions_user_identifier", "").strip()
        mentions_user_select = request.form.get("mentions_user_select", "").strip()
        mentions_max_results = request.form.get("mentions_max_results", "").strip()
        mentions_pagination_token = request.form.get("mentions_pagination_token", "").strip()
        mentions_since_id = request.form.get("mentions_since_id", "").strip()
        mentions_until_id = request.form.get("mentions_until_id", "").strip()
        mentions_start_time = request.form.get("mentions_start_time", "").strip()
        mentions_end_time = request.form.get("mentions_end_time", "").strip()
        home_max_results = request.form.get("home_max_results", "").strip()
        home_pagination_token = request.form.get("home_pagination_token", "").strip()
        home_since_id = request.form.get("home_since_id", "").strip()
        home_until_id = request.form.get("home_until_id", "").strip()
        home_start_time = request.form.get("home_start_time", "").strip()
        home_end_time = request.form.get("home_end_time", "").strip()
        home_exclude_replies = request.form.get("home_exclude_replies") == "on"
        home_exclude_retweets = request.form.get("home_exclude_retweets") == "on"
        reposts_max_results = request.form.get("reposts_max_results", "").strip()
        reposts_pagination_token = request.form.get("reposts_pagination_token", "").strip()
        curl_preview = None

        def parse_csv(value: str) -> list[str]:
            return [item.strip() for item in value.split(",") if item.strip()]

        def parse_poll_options(value: str) -> list[str]:
            if "\n" in value:
                return [item.strip() for item in value.splitlines() if item.strip()]
            return parse_csv(value)

        def build_curl(
            url: str,
            method: str = "GET",
            params_dict: dict | None = None,
            payload: dict | None = None,
        ) -> str:
            parts = ['curl -H "Authorization: Bearer <token>"']
            if method != "GET":
                parts.append(f"-X {method}")
            if payload is not None:
                parts.append(f"-d '{json.dumps(payload, indent=2)}'")
            if params_dict:
                query = urlencode(params_dict, safe=",")
                return " ".join(parts + [f'"{url}?{query}"'])
            return " ".join(parts + [f'"{url}"'])

        action = request.form.get("posts_action")
        response = None
        if action == "create_post":
            if post_schedule_time:
                error = "Scheduling is not available in X API v2 yet."
                flash(error, "warning")
            else:
                media_ids = parse_csv(post_media_ids)
                media_ids.extend([item for item in post_media_select if item])
                poll_options = parse_poll_options(post_poll_options)
                conflicts = []
                if post_card_uri and (post_quote_tweet_id or poll_options or media_ids or post_direct_message_deep_link):
                    conflicts.append("card_uri cannot be combined with quote, poll, media, or DM deep links.")
                if poll_options and (media_ids or post_quote_tweet_id or post_card_uri):
                    conflicts.append("poll cannot be combined with media, quote, or card URI.")
                if media_ids and (post_quote_tweet_id or post_card_uri or poll_options):
                    conflicts.append("media cannot be combined with quote, card URI, or poll.")
                if conflicts:
                    error = " ".join(conflicts)
                    flash(error, "warning")
                else:
                    payload: dict[str, Any] = {}
                    if post_text:
                        payload["text"] = post_text
                    if post_card_uri:
                        payload["card_uri"] = post_card_uri
                    if post_direct_message_deep_link:
                        payload["direct_message_deep_link"] = post_direct_message_deep_link
                    if post_quote_tweet_id:
                        payload["quote_tweet_id"] = post_quote_tweet_id
                    if post_community_id:
                        payload["community_id"] = post_community_id
                    if post_geo_place_id:
                        payload["geo"] = {"place_id": post_geo_place_id}
                    if post_reply_settings:
                        payload["reply_settings"] = post_reply_settings
                    if post_for_super_followers_only:
                        payload["for_super_followers_only"] = True
                    if post_nullcast:
                        payload["nullcast"] = True
                    if post_share_with_followers:
                        payload["share_with_followers"] = True
                    if media_ids:
                        media_payload = {"media_ids": media_ids}
                        tagged_ids = parse_csv(post_media_tagged_user_ids)
                        if tagged_ids:
                            media_payload["tagged_user_ids"] = tagged_ids
                        payload["media"] = media_payload
                    if poll_options:
                        try:
                            duration = int(post_poll_duration) if post_poll_duration else None
                        except ValueError:
                            duration = None
                        if duration is None:
                            error = "Poll duration is required when adding poll options."
                            flash(error, "warning")
                        else:
                            poll_payload = {"options": poll_options, "duration_minutes": duration}
                            if post_poll_reply_settings:
                                poll_payload["reply_settings"] = post_poll_reply_settings
                            payload["poll"] = poll_payload
                    if post_reply_to_id:
                        reply_payload = {"in_reply_to_tweet_id": post_reply_to_id}
                        if post_reply_auto_metadata:
                            reply_payload["auto_populate_reply_metadata"] = True
                        exclude_ids = parse_csv(post_reply_exclude_user_ids)
                        if exclude_ids:
                            reply_payload["exclude_reply_user_ids"] = exclude_ids
                        payload["reply"] = reply_payload
                    if post_edit_previous_id:
                        payload["edit_options"] = {"previous_post_id": post_edit_previous_id}

                    if error is None and not payload:
                        error = "Provide text or add a poll/media/quote to create a post."
                        flash(error, "warning")
                    elif error is None:
                        flash("Post request started.", "info")
                        response = create_x_post(payload)
                        curl_preview = build_curl(
                            "https://api.x.com/2/tweets",
                            method="POST",
                            payload=payload,
                        )
        elif action == "delete_post":
            if not delete_post_id:
                error = "Please provide a post ID to delete."
                flash(error, "warning")
            else:
                flash("Delete post started.", "info")
                response = delete_x_post(delete_post_id)
                curl_preview = build_curl("https://api.x.com/2/tweets/<POST_ID>", method="DELETE")
        elif action == "repost_post":
            if not repost_post_id:
                error = "Please provide a post ID to repost."
                flash(error, "warning")
            else:
                flash("Repost started.", "info")
                response = repost_x_post(repost_post_id)
                curl_preview = build_curl(
                    "https://api.x.com/2/users/<ME>/retweets",
                    method="POST",
                    payload={"tweet_id": "<POST_ID>"},
                )
        elif action == "unrepost_post":
            if not repost_post_id:
                error = "Please provide a post ID to unrepost."
                flash(error, "warning")
            else:
                flash("Unrepost started.", "info")
                response = unrepost_x_post(repost_post_id)
                curl_preview = build_curl(
                    "https://api.x.com/2/users/<ME>/retweets/<POST_ID>",
                    method="DELETE",
                )
        elif action == "lookup_post":
            if not lookup_post_id:
                error = "Please provide a post ID or URL."
                flash(error, "warning")
            else:
                resolved_post_id, resolve_error = resolve_x_post_id(lookup_post_id)
                if resolve_error:
                    error = resolve_error
                    flash(resolve_error, "warning")
                else:
                    flash("Post lookup started.", "info")
                    response = get_x_post_by_id(resolved_post_id)
                    curl_preview = build_curl("https://api.x.com/2/tweets/<POST_ID>")
        elif action == "lookup_posts":
            if not lookup_post_ids:
                error = "Please provide post IDs."
                flash(error, "warning")
            else:
                ids = parse_csv(lookup_post_ids)
                if not ids:
                    error = "Please provide post IDs."
                    flash(error, "warning")
                else:
                    flash("Post lookup started.", "info")
                    response = get_x_posts_by_ids(ids)
                    curl_preview = build_curl(
                        "https://api.x.com/2/tweets",
                        params_dict={"ids": "ID1,ID2"},
                    )
        elif action == "quote_tweets":
            if not quote_post_id:
                error = "Please provide a post ID."
                flash(error, "warning")
            else:
                try:
                    max_results = int(quote_max_results) if quote_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 10), 100)
                exclude = []
                if quote_exclude_replies:
                    exclude.append("replies")
                if quote_exclude_retweets:
                    exclude.append("retweets")
                flash("Quote tweet lookup started.", "info")
                response = get_x_quote_tweets(
                    quote_post_id,
                    max_results=max_results,
                    pagination_token=quote_pagination_token or None,
                    exclude=exclude or None,
                )
                params = {"max_results": max_results}
                if quote_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                if exclude:
                    params["exclude"] = ",".join(exclude)
                curl_preview = build_curl("https://api.x.com/2/tweets/<POST_ID>/quote_tweets", params_dict=params)
        elif action == "search_recent":
            if not search_recent_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                try:
                    max_results = int(search_recent_max_results) if search_recent_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 10), 100)
                flash("Recent search started.", "info")
                response = search_x_posts_recent(
                    search_recent_query,
                    max_results=max_results,
                    start_time=search_recent_start_time or None,
                    end_time=search_recent_end_time or None,
                    since_id=search_recent_since_id or None,
                    until_id=search_recent_until_id or None,
                    next_token=search_recent_next_token or None,
                    pagination_token=search_recent_pagination_token or None,
                    sort_order=search_recent_sort_order or None,
                )
                params = {"query": "<QUERY>", "max_results": max_results}
                if search_recent_start_time:
                    params["start_time"] = "<START_TIME>"
                if search_recent_end_time:
                    params["end_time"] = "<END_TIME>"
                if search_recent_since_id:
                    params["since_id"] = "<SINCE_ID>"
                if search_recent_until_id:
                    params["until_id"] = "<UNTIL_ID>"
                if search_recent_next_token:
                    params["next_token"] = "<NEXT_TOKEN>"
                if search_recent_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                if search_recent_sort_order:
                    params["sort_order"] = search_recent_sort_order
                curl_preview = build_curl("https://api.x.com/2/tweets/search/recent", params_dict=params)
        elif action == "search_all":
            if not search_all_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                try:
                    max_results = int(search_all_max_results) if search_all_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 10), 500)
                flash("Full-archive search started.", "info")
                response = search_x_posts_all(
                    search_all_query,
                    max_results=max_results,
                    start_time=search_all_start_time or None,
                    end_time=search_all_end_time or None,
                    since_id=search_all_since_id or None,
                    until_id=search_all_until_id or None,
                    next_token=search_all_next_token or None,
                    pagination_token=search_all_pagination_token or None,
                    sort_order=search_all_sort_order or None,
                )
                params = {"query": "<QUERY>", "max_results": max_results}
                if search_all_start_time:
                    params["start_time"] = "<START_TIME>"
                if search_all_end_time:
                    params["end_time"] = "<END_TIME>"
                if search_all_since_id:
                    params["since_id"] = "<SINCE_ID>"
                if search_all_until_id:
                    params["until_id"] = "<UNTIL_ID>"
                if search_all_next_token:
                    params["next_token"] = "<NEXT_TOKEN>"
                if search_all_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                if search_all_sort_order:
                    params["sort_order"] = search_all_sort_order
                curl_preview = build_curl("https://api.x.com/2/tweets/search/all", params_dict=params)
        elif action == "counts_recent":
            if not counts_recent_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                flash("Recent counts started.", "info")
                response = get_x_posts_counts_recent(
                    counts_recent_query,
                    start_time=counts_recent_start_time or None,
                    end_time=counts_recent_end_time or None,
                    since_id=counts_recent_since_id or None,
                    until_id=counts_recent_until_id or None,
                    granularity=counts_recent_granularity or None,
                    next_token=counts_recent_next_token or None,
                    pagination_token=counts_recent_pagination_token or None,
                )
                params = {"query": "<QUERY>"}
                if counts_recent_start_time:
                    params["start_time"] = "<START_TIME>"
                if counts_recent_end_time:
                    params["end_time"] = "<END_TIME>"
                if counts_recent_since_id:
                    params["since_id"] = "<SINCE_ID>"
                if counts_recent_until_id:
                    params["until_id"] = "<UNTIL_ID>"
                if counts_recent_granularity:
                    params["granularity"] = counts_recent_granularity
                if counts_recent_next_token:
                    params["next_token"] = "<NEXT_TOKEN>"
                if counts_recent_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/tweets/counts/recent", params_dict=params)
        elif action == "counts_all":
            if not counts_all_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                flash("Full-archive counts started.", "info")
                response = get_x_posts_counts_all(
                    counts_all_query,
                    start_time=counts_all_start_time or None,
                    end_time=counts_all_end_time or None,
                    since_id=counts_all_since_id or None,
                    until_id=counts_all_until_id or None,
                    granularity=counts_all_granularity or None,
                    next_token=counts_all_next_token or None,
                    pagination_token=counts_all_pagination_token or None,
                )
                params = {"query": "<QUERY>"}
                if counts_all_start_time:
                    params["start_time"] = "<START_TIME>"
                if counts_all_end_time:
                    params["end_time"] = "<END_TIME>"
                if counts_all_since_id:
                    params["since_id"] = "<SINCE_ID>"
                if counts_all_until_id:
                    params["until_id"] = "<UNTIL_ID>"
                if counts_all_granularity:
                    params["granularity"] = counts_all_granularity
                if counts_all_next_token:
                    params["next_token"] = "<NEXT_TOKEN>"
                if counts_all_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                curl_preview = build_curl("https://api.x.com/2/tweets/counts/all", params_dict=params)
        elif action == "timeline_posts":
            identifier = timeline_user_select or timeline_user_identifier
            if not identifier:
                error = "Please provide a user ID or username."
                flash(error, "warning")
            else:
                try:
                    max_results = int(timeline_max_results) if timeline_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 5), 100)
                resolved_user_id, resolve_error = resolve_x_user_id(identifier)
                if resolve_error:
                    error = resolve_error
                    flash(resolve_error, "warning")
                else:
                    exclude = []
                    if timeline_exclude_replies:
                        exclude.append("replies")
                    if timeline_exclude_retweets:
                        exclude.append("retweets")
                    flash("Timeline lookup started.", "info")
                    response = get_x_user_posts(
                        resolved_user_id,
                        max_results=max_results,
                        pagination_token=timeline_pagination_token or None,
                        since_id=timeline_since_id or None,
                        until_id=timeline_until_id or None,
                        start_time=timeline_start_time or None,
                        end_time=timeline_end_time or None,
                        exclude=exclude or None,
                    )
                    params = {"max_results": max_results}
                    if timeline_pagination_token:
                        params["pagination_token"] = "<PAGINATION_TOKEN>"
                    if timeline_since_id:
                        params["since_id"] = "<SINCE_ID>"
                    if timeline_until_id:
                        params["until_id"] = "<UNTIL_ID>"
                    if timeline_start_time:
                        params["start_time"] = "<START_TIME>"
                    if timeline_end_time:
                        params["end_time"] = "<END_TIME>"
                    if exclude:
                        params["exclude"] = ",".join(exclude)
                    curl_preview = build_curl("https://api.x.com/2/users/<USER_ID>/tweets", params_dict=params)
        elif action == "mentions":
            identifier = mentions_user_select or mentions_user_identifier
            if not identifier:
                error = "Please provide a user ID or username."
                flash(error, "warning")
            else:
                try:
                    max_results = int(mentions_max_results) if mentions_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 5), 100)
                resolved_user_id, resolve_error = resolve_x_user_id(identifier)
                if resolve_error:
                    error = resolve_error
                    flash(resolve_error, "warning")
                else:
                    flash("Mentions lookup started.", "info")
                    response = get_x_user_mentions(
                        resolved_user_id,
                        max_results=max_results,
                        pagination_token=mentions_pagination_token or None,
                        since_id=mentions_since_id or None,
                        until_id=mentions_until_id or None,
                        start_time=mentions_start_time or None,
                        end_time=mentions_end_time or None,
                    )
                    params = {"max_results": max_results}
                    if mentions_pagination_token:
                        params["pagination_token"] = "<PAGINATION_TOKEN>"
                    if mentions_since_id:
                        params["since_id"] = "<SINCE_ID>"
                    if mentions_until_id:
                        params["until_id"] = "<UNTIL_ID>"
                    if mentions_start_time:
                        params["start_time"] = "<START_TIME>"
                    if mentions_end_time:
                        params["end_time"] = "<END_TIME>"
                    curl_preview = build_curl("https://api.x.com/2/users/<USER_ID>/mentions", params_dict=params)
        elif action == "home_timeline":
            active_x_user_id = session.get("active_x_user_id")
            if not active_x_user_id:
                error = "No active X account is selected."
                flash(error, "warning")
            else:
                try:
                    max_results = int(home_max_results) if home_max_results else 20
                except ValueError:
                    max_results = 20
                max_results = min(max(max_results, 1), 100)
                exclude = []
                if home_exclude_replies:
                    exclude.append("replies")
                if home_exclude_retweets:
                    exclude.append("retweets")
                flash("Home timeline lookup started.", "info")
                response = get_x_home_timeline(
                    active_x_user_id,
                    max_results=max_results,
                    pagination_token=home_pagination_token or None,
                    since_id=home_since_id or None,
                    until_id=home_until_id or None,
                    start_time=home_start_time or None,
                    end_time=home_end_time or None,
                    exclude=exclude or None,
                )
                params = {"max_results": max_results}
                if home_pagination_token:
                    params["pagination_token"] = "<PAGINATION_TOKEN>"
                if home_since_id:
                    params["since_id"] = "<SINCE_ID>"
                if home_until_id:
                    params["until_id"] = "<UNTIL_ID>"
                if home_start_time:
                    params["start_time"] = "<START_TIME>"
                if home_end_time:
                    params["end_time"] = "<END_TIME>"
                if exclude:
                    params["exclude"] = ",".join(exclude)
                curl_preview = build_curl(
                    "https://api.x.com/2/users/<ME>/timelines/reverse_chronological",
                    params_dict=params,
                )
        elif action == "reposts_of_me":
            try:
                max_results = int(reposts_max_results) if reposts_max_results else 100
            except ValueError:
                max_results = 100
            max_results = min(max(max_results, 1), 100)
            flash("Reposts of me lookup started.", "info")
            response = get_x_reposts_of_me(
                max_results=max_results,
                pagination_token=reposts_pagination_token or None,
            )
            params = {"max_results": max_results}
            if reposts_pagination_token:
                params["pagination_token"] = "<PAGINATION_TOKEN>"
            curl_preview = build_curl("https://api.x.com/2/users/reposts_of_me", params_dict=params)
        else:
            response = None
            error = "Please select a posts action to run."
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
                if response.get("error"):
                    error = response["error"]
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
                        "Your developer app may need elevated access or OAuth user context."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        log_id = session.get("x_last_api_log_id") if response is not None else None
        if isinstance(response, dict) and response.get("error") and not log_id:
            log_id = None
        session["x_posts_lookup_log_id"] = log_id
        session["x_posts_lookup_error"] = error
        session["x_posts_lookup_curl"] = curl_preview
        session["x_posts_known_limit"] = known_limit
        return redirect(url_for("x_api.posts"))

    return render_template(
        "x_api/posts.html",
        post_text=post_text,
        post_card_uri=post_card_uri,
        post_direct_message_deep_link=post_direct_message_deep_link,
        post_quote_tweet_id=post_quote_tweet_id,
        post_community_id=post_community_id,
        post_geo_place_id=post_geo_place_id,
        post_reply_settings=post_reply_settings,
        post_for_super_followers_only=post_for_super_followers_only,
        post_nullcast=post_nullcast,
        post_share_with_followers=post_share_with_followers,
        post_media_ids=post_media_ids,
        post_media_tagged_user_ids=post_media_tagged_user_ids,
        post_media_select=post_media_select,
        post_poll_options=post_poll_options,
        post_poll_duration=post_poll_duration,
        post_poll_reply_settings=post_poll_reply_settings,
        post_reply_to_id=post_reply_to_id,
        post_reply_auto_metadata=post_reply_auto_metadata,
        post_reply_exclude_user_ids=post_reply_exclude_user_ids,
        post_edit_previous_id=post_edit_previous_id,
        post_schedule_time=post_schedule_time,
        delete_post_id=delete_post_id,
        repost_post_id=repost_post_id,
        lookup_post_id=lookup_post_id,
        lookup_post_ids=lookup_post_ids,
        quote_post_id=quote_post_id,
        quote_max_results=quote_max_results,
        quote_pagination_token=quote_pagination_token,
        quote_exclude_replies=quote_exclude_replies,
        quote_exclude_retweets=quote_exclude_retweets,
        search_recent_query=search_recent_query,
        search_recent_start_time=search_recent_start_time,
        search_recent_end_time=search_recent_end_time,
        search_recent_since_id=search_recent_since_id,
        search_recent_until_id=search_recent_until_id,
        search_recent_max_results=search_recent_max_results,
        search_recent_next_token=search_recent_next_token,
        search_recent_pagination_token=search_recent_pagination_token,
        search_recent_sort_order=search_recent_sort_order,
        search_all_query=search_all_query,
        search_all_start_time=search_all_start_time,
        search_all_end_time=search_all_end_time,
        search_all_since_id=search_all_since_id,
        search_all_until_id=search_all_until_id,
        search_all_max_results=search_all_max_results,
        search_all_next_token=search_all_next_token,
        search_all_pagination_token=search_all_pagination_token,
        search_all_sort_order=search_all_sort_order,
        counts_recent_query=counts_recent_query,
        counts_recent_start_time=counts_recent_start_time,
        counts_recent_end_time=counts_recent_end_time,
        counts_recent_since_id=counts_recent_since_id,
        counts_recent_until_id=counts_recent_until_id,
        counts_recent_granularity=counts_recent_granularity,
        counts_recent_next_token=counts_recent_next_token,
        counts_recent_pagination_token=counts_recent_pagination_token,
        counts_all_query=counts_all_query,
        counts_all_start_time=counts_all_start_time,
        counts_all_end_time=counts_all_end_time,
        counts_all_since_id=counts_all_since_id,
        counts_all_until_id=counts_all_until_id,
        counts_all_granularity=counts_all_granularity,
        counts_all_next_token=counts_all_next_token,
        counts_all_pagination_token=counts_all_pagination_token,
        timeline_user_identifier=timeline_user_identifier,
        timeline_user_select=timeline_user_select,
        timeline_max_results=timeline_max_results,
        timeline_pagination_token=timeline_pagination_token,
        timeline_since_id=timeline_since_id,
        timeline_until_id=timeline_until_id,
        timeline_start_time=timeline_start_time,
        timeline_end_time=timeline_end_time,
        timeline_exclude_replies=timeline_exclude_replies,
        timeline_exclude_retweets=timeline_exclude_retweets,
        mentions_user_identifier=mentions_user_identifier,
        mentions_user_select=mentions_user_select,
        mentions_max_results=mentions_max_results,
        mentions_pagination_token=mentions_pagination_token,
        mentions_since_id=mentions_since_id,
        mentions_until_id=mentions_until_id,
        mentions_start_time=mentions_start_time,
        mentions_end_time=mentions_end_time,
        home_max_results=home_max_results,
        home_pagination_token=home_pagination_token,
        home_since_id=home_since_id,
        home_until_id=home_until_id,
        home_start_time=home_start_time,
        home_end_time=home_end_time,
        home_exclude_replies=home_exclude_replies,
        home_exclude_retweets=home_exclude_retweets,
        reposts_max_results=reposts_max_results,
        reposts_pagination_token=reposts_pagination_token,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        existing_users=XUser.query.order_by(XUser.username.asc()).limit(200).all(),
        existing_posts=XPost.query.order_by(XPost.created_at.desc()).limit(200).all(),
        media_uploads=XMediaUpload.query.filter_by(user_id=session.get("user_id")).order_by(XMediaUpload.created_at.desc()).limit(200).all(),
        tweet_fields=_filter_fields(TWEET_FIELDS),
        user_fields=_filter_fields(USER_FIELDS),
        media_fields=_filter_fields(MEDIA_FIELDS),
        poll_fields=_filter_fields(POLL_FIELDS),
        place_fields=_filter_fields(PLACE_FIELDS),
        search_count_fields=_filter_fields(SEARCH_COUNT_FIELDS),
    )


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


@bp.route("/trends", methods=["GET", "POST"])
@login_required
def trends():
    woeid_input = ""
    woeid_select = ""
    max_trends = ""
    result = None
    keep_result = session.pop("x_trends_keep_result", False)
    if request.method == "GET" and not keep_result:
        session.pop("x_trends_lookup_log_id", None)
        session.pop("x_trends_lookup_error", None)
        session.pop("x_trends_known_limit", None)
        session.pop("x_trends_lookup_curl", None)
    error = session.get("x_trends_lookup_error")
    known_limit = session.get("x_trends_known_limit")
    curl_preview = session.get("x_trends_lookup_curl")
    log_id = session.get("x_trends_lookup_log_id")

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

    existing_woeids = (
        XTrendSnapshot.query.with_entities(XTrendSnapshot.woeid)
        .filter(XTrendSnapshot.woeid.isnot(None))
        .distinct()
        .order_by(XTrendSnapshot.woeid.asc())
        .limit(200)
        .all()
    )
    known_woeids = [row.woeid for row in existing_woeids if row.woeid is not None]
    common_woeids = [
        (1, "Worldwide"),
        (23424977, "United States"),
        (23424775, "Canada"),
        (23424856, "United Kingdom"),
        (23424848, "Spain"),
        (23424829, "Germany"),
        (23424803, "India"),
        (23424747, "Brazil"),
        (23424900, "Mexico"),
        (23424868, "Australia"),
        (23424853, "France"),
        (23424846, "South Korea"),
        (23424852, "Italy"),
        (23424860, "Indonesia"),
    ]

    if request.method == "POST":
        known_limit = None
        woeid_input = request.form.get("woeid_input", "").strip()
        woeid_select = request.form.get("woeid_select", "").strip()
        max_trends = request.form.get("max_trends", "").strip()
        curl_preview = None

        def build_curl(url: str, params_dict: dict | None = None) -> str:
            if not params_dict:
                return f'curl -H "Authorization: Bearer <token>" "{url}"'
            query = urlencode(params_dict, safe=",")
            return f'curl -H "Authorization: Bearer <token>" "{url}?{query}"'

        action = request.form.get("trends_action")
        response = None
        if action == "trends_by_woeid":
            woeid_value = woeid_input or woeid_select
            if not woeid_value:
                error = "Please provide a WOEID."
                flash(error, "warning")
            else:
                try:
                    woeid = int(woeid_value)
                except ValueError:
                    error = "WOEID must be a number."
                    flash(error, "warning")
                    woeid = None
                if woeid is not None:
                    try:
                        max_value = int(max_trends) if max_trends else 20
                    except ValueError:
                        max_value = 20
                    max_value = min(max(max_value, 1), 50)
                    flash("Trends lookup started.", "info")
                    response = get_x_trends_by_woeid(woeid, max_trends=max_value)
                    params = {
                        "max_trends": max_value,
                        "trend.fields": ",".join(_filter_fields(TREND_FIELDS)),
                    }
                    curl_preview = build_curl("https://api.x.com/2/trends/by/woeid/<WOEID>", params)
        elif action == "personalized_trends":
            flash("Personalized trends lookup started.", "info")
            response = get_x_personalized_trends()
            params = {
                "personalized_trend.fields": ",".join(_filter_fields(PERSONALIZED_TREND_FIELDS)),
            }
            curl_preview = build_curl("https://api.x.com/2/users/personalized_trends", params)
        else:
            response = None
            error = "Please select a trends action to run."
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
                        "Trends endpoints may require elevated or app-only access."
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
                        "Trends endpoints may require elevated or app-only access."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        session["x_trends_keep_result"] = True
        log_id = session.get("x_last_api_log_id")
        if isinstance(response, dict) and response.get("error") and not log_id:
            log_id = None
        session["x_trends_lookup_log_id"] = log_id
        session["x_trends_lookup_error"] = error
        session["x_trends_lookup_curl"] = curl_preview
        session["x_trends_known_limit"] = known_limit
        return redirect(url_for("x_api.trends"))

    return render_template(
        "x_api/trends.html",
        woeid_input=woeid_input,
        woeid_select=woeid_select,
        max_trends=max_trends,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        known_woeids=known_woeids,
        common_woeids=common_woeids,
    )


@bp.route("/news", methods=["GET", "POST"])
@login_required
def news():
    news_id = ""
    search_query = ""
    search_max_results = ""
    search_max_age_hours = ""
    result = None
    keep_result = session.pop("x_news_keep_result", False)
    if request.method == "GET" and not keep_result:
        session.pop("x_news_lookup_log_id", None)
        session.pop("x_news_lookup_error", None)
        session.pop("x_news_known_limit", None)
        session.pop("x_news_lookup_curl", None)
    error = session.get("x_news_lookup_error")
    known_limit = session.get("x_news_known_limit")
    curl_preview = session.get("x_news_lookup_curl")
    log_id = session.get("x_news_lookup_log_id")

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

    recent_news = (
        XNewsStorySnapshot.query.order_by(XNewsStorySnapshot.fetched_at.desc())
        .limit(200)
        .all()
    )

    if request.method == "POST":
        known_limit = None
        news_id = request.form.get("news_id", "").strip()
        search_query = request.form.get("search_query", "").strip()
        search_max_results = request.form.get("search_max_results", "").strip()
        search_max_age_hours = request.form.get("search_max_age_hours", "").strip()
        curl_preview = None

        def build_curl(url: str, params_dict: dict | None = None) -> str:
            if not params_dict:
                return f'curl -H "Authorization: Bearer <token>" "{url}"'
            query = urlencode(params_dict, safe=",")
            return f'curl -H "Authorization: Bearer <token>" "{url}?{query}"'

        action = request.form.get("news_action")
        response = None
        if action == "news_by_id":
            if not news_id:
                error = "Please provide a news ID."
                flash(error, "warning")
            else:
                flash("News lookup started.", "info")
                response = get_x_news_by_id(news_id)
                params = {"news.fields": ",".join(_filter_fields(NEWS_FIELDS))}
                curl_preview = build_curl("https://api.x.com/2/news/<ID>", params)
        elif action == "search_news":
            if not search_query:
                error = "Please provide a search query."
                flash(error, "warning")
            else:
                try:
                    max_results = int(search_max_results) if search_max_results else 10
                except ValueError:
                    max_results = 10
                max_results = min(max(max_results, 1), 100)
                try:
                    max_age_hours = int(search_max_age_hours) if search_max_age_hours else 168
                except ValueError:
                    max_age_hours = 168
                max_age_hours = min(max(max_age_hours, 1), 720)
                flash("News search started.", "info")
                response = search_x_news(
                    search_query,
                    max_results=max_results,
                    max_age_hours=max_age_hours,
                )
                params = {
                    "query": "<QUERY>",
                    "max_results": max_results,
                    "max_age_hours": max_age_hours,
                    "news.fields": ",".join(_filter_fields(NEWS_FIELDS)),
                }
                curl_preview = build_curl("https://api.x.com/2/news/search", params)
        else:
            response = None
            error = "Please select a news action to run."
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
                        "News endpoints can require app-only access."
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
                        "News endpoints can require app-only access."
                    )
                    error = known_limit
                    flash(known_limit, "warning")
                if response.status_code and response.status_code >= 400:
                    flash(f"Lookup failed with status {response.status_code}.", "danger")
                else:
                    flash("Lookup complete.", "success")

        session["x_news_keep_result"] = True
        log_id = session.get("x_last_api_log_id")
        if isinstance(response, dict) and response.get("error") and not log_id:
            log_id = None
        session["x_news_lookup_log_id"] = log_id
        session["x_news_lookup_error"] = error
        session["x_news_lookup_curl"] = curl_preview
        session["x_news_known_limit"] = known_limit
        return redirect(url_for("x_api.news"))

    return render_template(
        "x_api/news.html",
        news_id=news_id,
        search_query=search_query,
        search_max_results=search_max_results,
        search_max_age_hours=search_max_age_hours,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        recent_news=recent_news,
    )


@bp.route("/media/<int:upload_id>/file")
@login_required
def media_file(upload_id: int):
    upload = XMediaUpload.query.filter_by(id=upload_id, user_id=session.get("user_id")).first()
    if not upload or not upload.file_blob:
        return jsonify({"error": "Media not found."}), 404
    return send_file(
        io.BytesIO(upload.file_blob),
        mimetype=upload.content_type or "application/octet-stream",
        as_attachment=False,
        download_name=upload.filename or f"media-{upload.id}",
    )


@bp.route("/media", methods=["GET", "POST"])
@login_required
def media():
    media_id = ""
    result = None
    error = session.get("x_media_lookup_error")
    curl_preview = session.get("x_media_lookup_curl")
    log_id = session.get("x_media_lookup_log_id")
    known_limit = session.get("x_media_known_limit")
    keep_result = session.pop("x_media_keep_result", False)
    if request.method == "GET" and not keep_result:
        session.pop("x_media_lookup_log_id", None)
        session.pop("x_media_lookup_error", None)
        session.pop("x_media_known_limit", None)
        session.pop("x_media_lookup_curl", None)
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

    recent_uploads = (
        XMediaUpload.query.filter_by(user_id=session.get("user_id"))
        .order_by(XMediaUpload.created_at.desc())
        .limit(50)
        .all()
    )

    def parse_response(response: Any) -> tuple[dict, int | None]:
        if isinstance(response, dict):
            return response, None
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        return payload, response.status_code

    if request.method == "POST":
        known_limit = None
        action = request.form.get("media_action")
        response = None
        curl_preview = None
        if action == "status":
            media_id = request.form.get("media_id", "").strip()
            if not media_id:
                error = "Please provide a media ID."
                flash(error, "warning")
            else:
                flash("Status lookup started.", "info")
                response = get_x_media_upload_status(media_id)
                curl_preview = (
                    'curl -H "Authorization: Bearer <token>" '
                    f'"https://api.x.com/2/media/upload?command=STATUS&media_id={media_id}"'
                )
        elif action == "upload":
            upload_file = request.files.get("media_file")
            if not upload_file or not upload_file.filename:
                error = "Please choose a media file to upload."
                flash(error, "warning")
            else:
                filename = upload_file.filename
                original_bytes = upload_file.read()
                content_type = upload_file.mimetype or "application/octet-stream"
                media_category = request.form.get("media_category", "tweet_image").strip()
                media_type = request.form.get("media_type", "").strip() or content_type
                output_format = request.form.get("output_format", "").strip().lower() or None
                shared = request.form.get("shared") == "on"

                def parse_int(value: str) -> int | None:
                    try:
                        return int(value) if value else None
                    except ValueError:
                        return None

                width = parse_int(request.form.get("resize_width", "").strip())
                height = parse_int(request.form.get("resize_height", "").strip())
                quality = parse_int(request.form.get("quality", "").strip())

                processed_bytes = original_bytes
                processed_format = None
                stored_content_type = content_type
                stored_width = None
                stored_height = None
                is_image = content_type.startswith("image/")
                is_gif = content_type == "image/gif"
                if is_image and not is_gif:
                    processed_bytes, processed_format, stored_content_type, stored_width, stored_height = _process_image_bytes(
                        original_bytes,
                        output_format,
                        width,
                        height,
                        quality,
                    )

                upload_mode = "oneshot"
                if content_type.startswith("video/") or is_gif or len(processed_bytes) > 5 * 1024 * 1024:
                    upload_mode = "chunked"

                record = XMediaUpload(
                    user_id=session.get("user_id"),
                    x_user_id=session.get("active_x_user_id"),
                    filename=filename,
                    content_type=stored_content_type,
                    media_category=media_category,
                    media_type=media_type,
                    output_format=processed_format,
                    width=stored_width,
                    height=stored_height,
                    file_size=len(original_bytes),
                    stored_size=len(processed_bytes),
                    upload_mode=upload_mode,
                    status="pending",
                )
                db.session.add(record)
                db.session.flush()

                if upload_mode == "oneshot":
                    flash("Upload started.", "info")
                    response = upload_x_media_one_shot(
                        processed_bytes,
                        filename=filename,
                        media_category=media_category,
                        media_type=media_type,
                        shared=shared,
                    )
                    curl_parts = [
                        'curl -X POST "https://api.x.com/2/media/upload"',
                        '-H "Authorization: Bearer <token>"',
                        '-H "Content-Type: multipart/form-data"',
                        '-F "media=@/path/to/file"',
                        f'-F "media_category={media_category}"',
                    ]
                    if media_type:
                        curl_parts.append(f'-F "media_type={media_type}"')
                    if shared:
                        curl_parts.append('-F "shared=true"')
                    curl_preview = " \\\n  ".join(curl_parts)
                else:
                    flash("Chunked upload started.", "info")
                    init_response = initialize_x_media_upload(
                        total_bytes=len(processed_bytes),
                        media_type=media_type,
                        media_category=media_category,
                        shared=shared,
                    )
                    init_payload, init_status = parse_response(init_response)
                    record.raw_response = init_payload
                    media_id_value = (init_payload.get("data") or {}).get("id")
                    if init_status and init_status >= 400:
                        record.status = "failed"
                        record.error_message = f"INIT failed with status {init_status}."
                        response = init_response
                    elif init_payload.get("error") or not media_id_value:
                        record.status = "failed"
                        record.error_message = init_payload.get("error") or "INIT failed."
                        response = init_response
                    else:
                        chunk_size = 2 * 1024 * 1024
                        for index in range(0, len(processed_bytes), chunk_size):
                            chunk = processed_bytes[index:index + chunk_size]
                            segment_index = index // chunk_size
                            append_response = append_x_media_upload(
                                media_id=str(media_id_value),
                                segment_index=segment_index,
                                chunk_bytes=chunk,
                            )
                            append_payload, append_status = parse_response(append_response)
                            if append_status and append_status >= 400:
                                record.status = "failed"
                                record.error_message = f"APPEND failed with status {append_status}."
                                response = append_response
                                break
                            if append_payload.get("error"):
                                record.status = "failed"
                                record.error_message = append_payload.get("error")
                                response = append_response
                                break
                        if record.status != "failed":
                            finalize_response = finalize_x_media_upload(str(media_id_value))
                            finalize_payload, finalize_status = parse_response(finalize_response)
                            record.raw_response = finalize_payload
                            response = finalize_response
                            if finalize_status and finalize_status >= 400:
                                record.status = "failed"
                                record.error_message = f"FINALIZE failed with status {finalize_status}."
                            elif finalize_payload.get("error"):
                                record.status = "failed"
                                record.error_message = finalize_payload.get("error")
                            else:
                                record.status = "uploaded"

                    curl_preview = (
                        'curl -X POST "https://api.x.com/2/media/upload" '
                        '-H "Authorization: Bearer <token>" '
                        '-H "Content-Type: multipart/form-data" '
                        f'-F "command=INIT" -F "media_type={media_type}" '
                        f'-F "total_bytes={len(processed_bytes)}" '
                        + (f'-F "media_category={media_category}" ' if media_category else "")
                    ).strip()

                payload, status_code = parse_response(response) if response is not None else ({}, None)
                record.raw_response = payload
                if payload.get("data"):
                    record.media_id = payload["data"].get("id") or record.media_id
                    record.media_key = payload["data"].get("media_key") or record.media_key
                    processing = payload["data"].get("processing_info") or {}
                    if processing.get("state") in {"pending", "in_progress"}:
                        record.status = "processing"
                    elif record.status not in {"failed"}:
                        record.status = "uploaded"
                if status_code and status_code >= 400:
                    record.status = "failed"
                    record.error_message = f"Upload failed with status {status_code}."
                if payload.get("error"):
                    record.status = "failed"
                    record.error_message = payload.get("error")
                if record.status not in {"failed"} and payload.get("data"):
                    record.file_blob = processed_bytes

                db.session.commit()
                recent_uploads = (
                    XMediaUpload.query.filter_by(user_id=session.get("user_id"))
                    .order_by(XMediaUpload.created_at.desc())
                    .limit(50)
                    .all()
                )

                if record.status == "failed":
                    error = record.error_message or "Upload failed."
                    flash(error, "warning")
                else:
                    flash("Upload complete.", "success")
        else:
            error = "Please select a media action to run."
            flash(error, "warning")

        if response is None and error is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        elif response is not None:
            result, _ = parse_response(response)
            if isinstance(response, dict) and response.get("error"):
                flash(response["error"], "warning")
            elif not error:
                flash("Lookup complete.", "success")

        session["x_media_keep_result"] = True
        log_id = session.get("x_last_api_log_id")
        if isinstance(response, dict) and response.get("error") and not log_id:
            log_id = None
        session["x_media_lookup_log_id"] = log_id
        session["x_media_lookup_error"] = error
        session["x_media_lookup_curl"] = curl_preview
        session["x_media_known_limit"] = known_limit
        return redirect(url_for("x_api.media"))

    return render_template(
        "x_api/media.html",
        media_id=media_id,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        recent_uploads=recent_uploads,
        image_format_options=sorted(set(value[0].lower() for value in IMAGE_FORMATS.values())),
    )


@bp.route("/usage", methods=["GET", "POST"])
@login_required
def usage():
    time_value = ""
    time_unit = "hours"
    days = ""
    result = None
    error = session.get("x_usage_lookup_error")
    known_limit = session.get("x_usage_known_limit")
    curl_preview = session.get("x_usage_lookup_curl")
    log_id = session.get("x_usage_lookup_log_id")
    keep_result = session.pop("x_usage_keep_result", False)
    if request.method == "GET" and not keep_result:
        session.pop("x_usage_lookup_log_id", None)
        session.pop("x_usage_lookup_error", None)
        session.pop("x_usage_known_limit", None)
        session.pop("x_usage_lookup_curl", None)
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

    snapshots = (
        XUsageSnapshot.query.filter_by(user_id=session.get("user_id"))
        .order_by(XUsageSnapshot.created_at.desc())
        .limit(50)
        .all()
    )

    if request.method == "POST":
        known_limit = None
        time_value = request.form.get("time_value", "").strip()
        time_unit = request.form.get("time_unit", "hours").strip() or "hours"
        days = request.form.get("days", "").strip()
        curl_preview = None

        def parse_int(raw_value: str, default: int) -> int:
            try:
                return int(raw_value) if raw_value else default
            except ValueError:
                return default

        def clamp(value: int, min_value: int, max_value: int) -> int:
            return min(max(value, min_value), max_value)

        hours_value = None
        if time_unit == "hours":
            hours_value = clamp(parse_int(time_value, 24), 1, 2160)
            days_value = max(1, (hours_value + 23) // 24)
        else:
            days_value = clamp(parse_int(time_value or days, 1), 1, 90)

        if days and time_unit != "hours":
            days_value = clamp(parse_int(days, days_value), 1, 90)

        flash("Usage lookup started.", "info")
        response = get_x_usage_tweets(days=days_value, hours=hours_value)
        params = {"days": days_value, "usage.fields": ",".join(_filter_fields(USAGE_FIELDS))}
        curl_preview = f'curl -H "Authorization: Bearer <token>" "https://api.x.com/2/usage/tweets?{urlencode(params, safe=",")}"'

        if response is None:
            error = "Unable to call X API; check your credentials."
            result = None
            flash("Lookup failed. Check your credentials.", "danger")
        else:
            if isinstance(response, dict):
                result = response
                if response.get("error"):
                    error = response["error"]
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

        session["x_usage_keep_result"] = True
        log_id = session.get("x_last_api_log_id")
        if isinstance(response, dict) and response.get("error") and not log_id:
            log_id = None
        session["x_usage_lookup_log_id"] = log_id
        session["x_usage_lookup_error"] = error
        session["x_usage_lookup_curl"] = curl_preview
        session["x_usage_known_limit"] = known_limit
        return redirect(url_for("x_api.usage"))

    return render_template(
        "x_api/usage.html",
        time_value=time_value,
        time_unit=time_unit,
        days=days,
        result=result,
        error=error,
        known_limit=known_limit,
        curl_preview=curl_preview,
        snapshots=snapshots,
    )


@bp.route("/usage/data")
@login_required
def usage_data():
    draw = request.args.get("draw", type=int, default=1)
    start = request.args.get("start", type=int, default=0)
    length = request.args.get("length", type=int, default=10)
    search_value = request.args.get("search[value]", type=str, default="").strip()
    order_column = request.args.get("order[0][column]", type=int, default=0)
    order_dir = request.args.get("order[0][dir]", type=str, default="desc")

    query = XUsageSnapshot.query.filter_by(user_id=session.get("user_id"))
    total_count = query.count()

    if search_value:
        like_value = f"%{search_value}%"
        query = query.filter(
            or_(
                cast(XUsageSnapshot.project_id, String).ilike(like_value),
                cast(XUsageSnapshot.project_usage, String).ilike(like_value),
                cast(XUsageSnapshot.project_cap, String).ilike(like_value),
                cast(XUsageSnapshot.days, String).ilike(like_value),
            )
        )

    filtered_count = query.count()

    columns = [
        XUsageSnapshot.created_at,
        XUsageSnapshot.days,
        XUsageSnapshot.project_usage,
        XUsageSnapshot.project_cap,
        XUsageSnapshot.project_id,
    ]
    sort_column = columns[order_column] if order_column < len(columns) else XUsageSnapshot.created_at
    if order_dir == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    rows = query.offset(start).limit(length).all()

    data = []
    for row in rows:
        data.append({
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "days": row.days,
            "project_usage": row.project_usage,
            "project_cap": row.project_cap,
            "project_id": row.project_id,
            "id": row.id,
        })

    return jsonify({
        "draw": draw,
        "recordsTotal": total_count,
        "recordsFiltered": filtered_count,
        "data": data,
    })


@bp.route("/usage/<int:snapshot_id>")
@login_required
def usage_snapshot(snapshot_id: int):
    snapshot = XUsageSnapshot.query.filter_by(id=snapshot_id, user_id=session.get("user_id")).first()
    if not snapshot:
        return jsonify({"error": "Snapshot not found."}), 404
    return jsonify({
        "id": snapshot.id,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "days": snapshot.days,
        "hours": snapshot.hours,
        "cap_reset_day": snapshot.cap_reset_day,
        "project_cap": snapshot.project_cap,
        "project_id": snapshot.project_id,
        "project_usage": snapshot.project_usage,
        "raw_usage_data": snapshot.raw_usage_data,
    })


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
