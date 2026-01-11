import json
from datetime import datetime
from typing import Any, Mapping

import requests

from app.extensions import db
from app.models import ApiRequestLog, AnnotationDomain, AnnotationEntity, PostContextAnnotation, User, XPost, XUser
from flask import session

from app.blueprints.auth.token_helpers import call_x_api_with_refresh
from app.utils.encrypt_decrypt import get_app_var


EXCLUDED_FIELD_SUBSTRINGS = (
    "private",
    "protected",
    "non_public",
    "organic_metrics",
    "promoted_metrics",
)

TWEET_FIELDS = [
    "article",
    "attachments",
    "author_id",
    "card_uri",
    "community_id",
    "context_annotations",
    "conversation_id",
    "created_at",
    "display_text_range",
    "edit_controls",
    "edit_history_tweet_ids",
    "entities",
    "geo",
    "id",
    "in_reply_to_user_id",
    "lang",
    "media_metadata",
    "non_public_metrics",
    "note_tweet",
    "organic_metrics",
    "possibly_sensitive",
    "promoted_metrics",
    "public_metrics",
    "referenced_tweets",
    "reply_settings",
    "scopes",
    "source",
    "suggested_source_links",
    "suggested_source_links_with_counts",
    "text",
    "withheld",
]

USER_FIELDS = [
    "created_at",
    "description",
    "entities",
    "id",
    "location",
    "name",
    "pinned_tweet_id",
    "profile_image_url",
    "public_metrics",
    "url",
    "username",
    "verified",
    "verified_type",
    "withheld",
]

EXPANSIONS = [
    "affiliation.user_id",
    "most_recent_tweet_id",
    "pinned_tweet_id",
]


def _filter_fields(fields: list[str]) -> list[str]:
    return [
        field
        for field in fields
        if not any(excluded in field for excluded in EXCLUDED_FIELD_SUBSTRINGS)
    ]


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_replied_to_post_id(payload: Mapping[str, Any]) -> int | None:
    for reference in payload.get("referenced_tweets", []) or []:
        if reference.get("type") == "replied_to":
            try:
                return int(reference.get("id"))
            except (TypeError, ValueError):
                return None
    return None


def _upsert_x_post(payload: Mapping[str, Any]) -> XPost | None:
    post_id = payload.get("id")
    if not post_id:
        return None
    try:
        post_id = int(post_id)
    except (TypeError, ValueError):
        return None

    record = db.session.get(XPost, post_id)
    if record is None:
        record = XPost(id=post_id)
        db.session.add(record)

    record.author_id = int(payload["author_id"]) if payload.get("author_id") else record.author_id
    record.text = payload.get("text") or record.text
    record.created_at = _parse_iso8601(payload.get("created_at")) or record.created_at
    record.lang = payload.get("lang")
    record.possibly_sensitive = payload.get("possibly_sensitive", record.possibly_sensitive)
    record.reply_settings = payload.get("reply_settings")
    record.conversation_id = int(payload["conversation_id"]) if payload.get("conversation_id") else record.conversation_id
    record.in_reply_to_post_id = _get_replied_to_post_id(payload) or record.in_reply_to_post_id

    metrics = payload.get("public_metrics") or {}
    record.repost_count = metrics.get("retweet_count", record.repost_count)
    record.reply_count = metrics.get("reply_count", record.reply_count)
    record.like_count = metrics.get("like_count", record.like_count)
    record.quote_count = metrics.get("quote_count", record.quote_count)
    record.bookmark_count = metrics.get("bookmark_count", record.bookmark_count)
    record.impression_count = metrics.get("impression_count", record.impression_count)

    record.raw_post_data = payload
    _upsert_context_annotations(record.id, payload.get("context_annotations") or [])
    return record


def _upsert_context_annotations(post_id: int, annotations: list[Mapping[str, Any]]) -> None:
    for annotation in annotations:
        domain = annotation.get("domain") or {}
        entity = annotation.get("entity") or {}
        domain_id = domain.get("id")
        entity_id = entity.get("id")
        if not domain_id or not entity_id:
            continue

        domain_record = db.session.get(AnnotationDomain, domain_id)
        if domain_record is None:
            domain_record = AnnotationDomain(id=domain_id)
            db.session.add(domain_record)
        domain_record.name = domain.get("name", domain_record.name)
        domain_record.description = domain.get("description", domain_record.description)

        entity_record = db.session.get(AnnotationEntity, entity_id)
        if entity_record is None:
            entity_record = AnnotationEntity(id=entity_id)
            db.session.add(entity_record)
        entity_record.name = entity.get("name", entity_record.name)
        entity_record.description = entity.get("description", entity_record.description)

        link = db.session.get(PostContextAnnotation, (post_id, domain_id, entity_id))
        if link is None:
            db.session.add(
                PostContextAnnotation(
                    post_id=post_id,
                    domain_id=domain_id,
                    entity_id=entity_id,
                )
            )


def _trim_response_body(body: str | None, limit: int = 20000) -> str | None:
    if body is None:
        return None
    return body[:limit]


def _log_api_request(
    method: str,
    url: str,
    status_code: int | None,
    response_body: str | None = None,
    commit: bool = False,
) -> ApiRequestLog:
    record = ApiRequestLog(
        user_id=session.get("user_id"),
        method=method,
        url=url,
        status_code=status_code,
        response_body=_trim_response_body(response_body),
    )
    db.session.add(record)
    db.session.flush()
    session["x_last_api_log_id"] = record.id
    if commit:
        db.session.commit()
    return record


def get_api_request_history(limit: int = 100) -> list[dict[str, Any]]:
    logs = (
        ApiRequestLog.query.order_by(ApiRequestLog.created_at.desc())
        .limit(limit)
        .all()
    )
    user_ids = {log.user_id for log in logs if log.user_id}
    users = {}
    if user_ids:
        users = {
            user.id: user.username
            for user in User.query.filter(User.id.in_(user_ids)).all()
        }

    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "username": users.get(log.user_id),
            "method": log.method,
            "url": log.url,
            "status_code": log.status_code,
            "created_at": log.created_at,
        }
        for log in logs
    ]


def _upsert_x_user(payload: Mapping[str, Any]) -> XUser | None:
    user_id = payload.get("id")
    if not user_id:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    record = db.session.get(XUser, user_id)
    if record is None:
        record = XUser(id=user_id)
        db.session.add(record)

    record.username = payload.get("username", record.username)
    record.name = payload.get("name", record.name)
    record.created_at = _parse_iso8601(payload.get("created_at")) or record.created_at
    record.description = payload.get("description")
    record.location = payload.get("location")
    record.url = payload.get("url")
    record.profile_image_url = payload.get("profile_image_url")
    record.verified = payload.get("verified", record.verified)
    record.verified_type = payload.get("verified_type")
    record.pinned_post_id = int(payload["pinned_tweet_id"]) if payload.get("pinned_tweet_id") else None
    record.most_recent_post_id = int(payload["most_recent_tweet_id"]) if payload.get("most_recent_tweet_id") else None

    metrics = payload.get("public_metrics") or {}
    record.followers_count = metrics.get("followers_count", record.followers_count)
    record.following_count = metrics.get("following_count", record.following_count)
    record.post_count = metrics.get("tweet_count", record.post_count)
    record.listed_count = metrics.get("listed_count", record.listed_count)
    record.like_count = metrics.get("like_count", record.like_count)
    record.media_count = metrics.get("media_count", record.media_count)
    record.raw_profile_data = payload

    return record


def print_x_key(payload: Mapping[str, Any], key: str) -> Any:
    """Print and return a specific key from an X API response payload."""
    value = payload.get(key)
    print(f"X API {key}: {value}")
    return value


def get_x_user_by_username(username: str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return None

    url = f"https://api.x.com/2/users/by/username/{username}"
    params = {
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        "expansions": ",".join(_filter_fields(EXPANSIONS)),
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, params=params, timeout=10)
    _log_api_request("GET", response.url, response.status_code, response.text)
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    _upsert_x_user(payload["data"])

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_user_by_id(user_id: str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return None

    cleaned = str(user_id).strip()
    if not cleaned:
        print("Provide a user id.")
        return None

    url = f"https://api.x.com/2/users/{cleaned}"
    params = {
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        "expansions": ",".join(_filter_fields(EXPANSIONS)),
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, params=params, timeout=10)
    _log_api_request("GET", response.url, response.status_code, response.text)
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    _upsert_x_user(payload["data"])

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_my_x_user() -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        "https://api.x.com/2/users/me",
        params={
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
            "expansions": ",".join(_filter_fields(EXPANSIONS)),
            "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            "https://api.x.com/2/users/me",
            None,
            json.dumps(response),
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        _log_api_request("GET", response.url, response.status_code, response.text, commit=True)
        return response
    _log_api_request("GET", response.url, response.status_code, response.text)

    _upsert_x_user(payload["data"])

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_users_by_usernames(usernames: list[str] | str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return None

    if isinstance(usernames, str):
        usernames = [item.strip() for item in usernames.split(",")]
    cleaned = [name.strip().lstrip("@") for name in usernames if name and name.strip()]
    if not cleaned:
        print("Provide at least one username.")
        return None
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    url = "https://api.x.com/2/users/by"
    params = {
        "usernames": ",".join(cleaned),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        "expansions": ",".join(_filter_fields(EXPANSIONS)),
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, params=params, timeout=10)
    _log_api_request("GET", response.url, response.status_code, response.text)
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_users_by_ids(user_ids: list[str] | str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return None

    if isinstance(user_ids, str):
        user_ids = [item.strip() for item in user_ids.split(",")]
    cleaned = [str(item).strip() for item in user_ids if str(item).strip()]
    if not cleaned:
        print("Provide at least one user id.")
        return None
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    url = "https://api.x.com/2/users"
    params = {
        "ids": ",".join(cleaned),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        "expansions": ",".join(_filter_fields(EXPANSIONS)),
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, params=params, timeout=10)
    _log_api_request("GET", response.url, response.status_code, response.text)
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_users_search(query: str, max_results: int = 100, next_token: str | None = None) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        "https://api.x.com/2/users/search",
        params={
            "query": query,
            "max_results": max_results,
            "next_token": next_token,
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
            "expansions": ",".join(_filter_fields(EXPANSIONS)),
            "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            "https://api.x.com/2/users/search",
            None,
            json.dumps(response),
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request("GET", response.url, response.status_code, response.text)
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response
