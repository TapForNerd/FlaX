import io
import json
import re
from datetime import datetime
from typing import Any, Mapping

import requests
from PIL import Image

from app.extensions import db
from app.models import ApiRequestLog, AnnotationDomain, AnnotationEntity, PostContextAnnotation, User, XMediaUpload, XNewsStorySnapshot, XPost, XSpace, XSpaceSnapshot, XTrendSnapshot, XUser
from flask import session

from app.blueprints.auth.token_helpers import call_x_api_with_refresh, get_current_user_token
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

LIST_FIELDS = [
    "created_at",
    "description",
    "follower_count",
    "id",
    "member_count",
    "name",
    "owner_id",
    "private",
]

LIST_EXPANSIONS = [
    "owner_id",
]

COMMUNITY_FIELDS = [
    "access",
    "created_at",
    "description",
    "id",
    "join_policy",
    "member_count",
    "name",
]

TREND_FIELDS = [
    "trend_name",
    "tweet_count",
]

PERSONALIZED_TREND_FIELDS = [
    "category",
    "post_count",
    "trend_name",
    "trending_since",
]

NEWS_FIELDS = [
    "category",
    "cluster_posts_results",
    "contexts",
    "disclaimer",
    "hook",
    "id",
    "keywords",
    "name",
    "summary",
    "updated_at",
]

TWEET_EXPANSIONS = [
    "author_id",
]

IMAGE_FORMATS = {
    "jpeg": ("JPEG", "image/jpeg"),
    "jpg": ("JPEG", "image/jpeg"),
    "png": ("PNG", "image/png"),
    "webp": ("WEBP", "image/webp"),
}

SPACE_FIELDS = [
    "created_at",
    "creator_id",
    "ended_at",
    "host_ids",
    "id",
    "invited_user_ids",
    "is_ticketed",
    "lang",
    "participant_count",
    "scheduled_start",
    "speaker_ids",
    "started_at",
    "state",
    "subscriber_count",
    "title",
    "topic_ids",
    "updated_at",
]

SPACE_EXPANSIONS = [
    "creator_id",
    "host_ids",
    "invited_user_ids",
    "speaker_ids",
    "topic_ids",
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


def _upsert_x_space(payload: Mapping[str, Any]) -> XSpace | None:
    space_id = payload.get("id")
    if not space_id:
        return None

    record = db.session.get(XSpace, space_id)
    if record is None:
        record = XSpace(id=space_id, state=payload.get("state") or "unknown")
        db.session.add(record)

    record.state = payload.get("state", record.state)
    record.title = payload.get("title", record.title)
    creator_id = payload.get("creator_id")
    try:
        record.creator_id = int(creator_id) if creator_id else record.creator_id
    except (TypeError, ValueError):
        record.creator_id = record.creator_id
    record.scheduled_start = _parse_iso8601(payload.get("scheduled_start")) or record.scheduled_start
    record.started_at = _parse_iso8601(payload.get("started_at")) or record.started_at
    record.ended_at = _parse_iso8601(payload.get("ended_at")) or record.ended_at
    record.participant_count = payload.get("participant_count", record.participant_count)
    record.subscriber_count = payload.get("subscriber_count", record.subscriber_count)
    record.lang = payload.get("lang", record.lang)
    record.is_ticketed = payload.get("is_ticketed", record.is_ticketed)
    record.raw_space_data = payload

    return record


def _record_space_snapshot(space: XSpace, payload: Mapping[str, Any], source: str) -> None:
    snapshot = XSpaceSnapshot(
        space_id=space.id,
        source=source,
        state=payload.get("state"),
        participant_count=payload.get("participant_count"),
        subscriber_count=payload.get("subscriber_count"),
        raw_space_data=payload,
    )
    db.session.add(snapshot)


def _store_trend_snapshots(
    trends: list[Mapping[str, Any]],
    source: str,
    woeid: int | None = None,
) -> None:
    for trend in trends:
        trend_name = trend.get("trend_name")
        if not trend_name:
            continue
        snapshot = XTrendSnapshot(
            woeid=woeid,
            source=source,
            trend_name=str(trend_name),
            tweet_count=trend.get("tweet_count"),
            post_count=trend.get("post_count"),
            category=trend.get("category"),
            trending_since=trend.get("trending_since"),
            raw_trend_data=trend,
        )
        db.session.add(snapshot)


def _store_news_snapshots(
    stories: list[Mapping[str, Any]],
    source: str,
) -> None:
    for story in stories:
        story_id = story.get("id") or story.get("rest_id")
        if not story_id:
            continue
        snapshot = XNewsStorySnapshot(
            news_id=str(story_id),
            source=source,
            name=story.get("name"),
            category=story.get("category"),
            summary=story.get("summary"),
            hook=story.get("hook"),
            disclaimer=story.get("disclaimer"),
            last_updated_at=_parse_iso8601(story.get("last_updated_at_ms") or story.get("updated_at")),
            raw_news_data=story,
        )
        db.session.add(snapshot)


def _process_image_bytes(
    file_bytes: bytes,
    output_format: str | None,
    width: int | None,
    height: int | None,
    quality: int | None,
) -> tuple[bytes, str, str, int | None, int | None]:
    image = Image.open(io.BytesIO(file_bytes))
    if width or height:
        target_width = width or int(image.width * (height / image.height))
        target_height = height or int(image.height * (width / image.width))
        image = image.resize((target_width, target_height), Image.LANCZOS)

    format_key = (output_format or image.format or "JPEG").lower()
    format_name, content_type = IMAGE_FORMATS.get(format_key, ("JPEG", "image/jpeg"))
    if format_name == "JPEG" and image.mode in {"RGBA", "P"}:
        image = image.convert("RGB")

    buffer = io.BytesIO()
    save_kwargs = {}
    if format_name in {"JPEG", "WEBP"} and quality:
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
    image.save(buffer, format_name, **save_kwargs)
    return buffer.getvalue(), format_name.lower(), content_type, image.width, image.height


def upload_x_media_one_shot(
    file_bytes: bytes,
    filename: str,
    media_category: str,
    media_type: str | None = None,
    shared: bool = False,
    additional_owners: list[str] | None = None,
) -> Any:
    data = {"media_category": media_category}
    if media_type:
        data["media_type"] = media_type
    if shared:
        data["shared"] = "true"
    if additional_owners:
        data["additional_owners"] = ",".join(additional_owners)

    files = {"media": (filename, file_bytes, media_type or "application/octet-stream")}
    response = call_x_api_with_refresh(
        requests.post,
        "https://api.x.com/2/media/upload",
        data=data,
        files=files,
        timeout=30,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            "https://api.x.com/2/media/upload",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    return response


def initialize_x_media_upload(
    total_bytes: int,
    media_type: str,
    media_category: str | None = None,
    shared: bool = False,
    additional_owners: list[str] | None = None,
) -> Any:
    data = {
        "command": "INIT",
        "total_bytes": str(total_bytes),
        "media_type": media_type,
    }
    if media_category:
        data["media_category"] = media_category
    if shared:
        data["shared"] = "true"
    if additional_owners:
        data["additional_owners"] = ",".join(additional_owners)

    response = call_x_api_with_refresh(
        requests.post,
        "https://api.x.com/2/media/upload",
        data=data,
        timeout=30,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            "https://api.x.com/2/media/upload",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    return response


def append_x_media_upload(
    media_id: str,
    segment_index: int,
    chunk_bytes: bytes,
) -> Any:
    data = {
        "command": "APPEND",
        "media_id": str(media_id),
        "segment_index": str(segment_index),
    }
    files = {"media": ("chunk", chunk_bytes, "application/octet-stream")}
    response = call_x_api_with_refresh(
        requests.post,
        "https://api.x.com/2/media/upload",
        data=data,
        files=files,
        timeout=60,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            "https://api.x.com/2/media/upload",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    return response


def finalize_x_media_upload(media_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.post,
        "https://api.x.com/2/media/upload",
        data={"command": "FINALIZE", "media_id": str(media_id)},
        timeout=30,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            "https://api.x.com/2/media/upload",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    return response


def get_x_media_upload_status(media_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        "https://api.x.com/2/media/upload",
        params={"command": "STATUS", "media_id": media_id},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            "https://api.x.com/2/media/upload",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    db.session.commit()
    return response


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


def _trim_response_body(body: str | None, limit: int = 200000) -> str | None:
    if body is None:
        return None
    return body[:limit]


def _log_api_request(
    method: str,
    url: str,
    status_code: int | None,
    response_body: str | None = None,
    response_headers: dict[str, Any] | None = None,
    commit: bool = False,
) -> ApiRequestLog:
    record = ApiRequestLog(
        user_id=session.get("user_id"),
        method=method,
        url=url,
        status_code=status_code,
        response_body=_trim_response_body(response_body),
        response_headers=response_headers,
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


def resolve_x_user_id(identifier: str | None) -> tuple[str | None, str | None]:
    """Resolve a username or user id into a numeric user id."""
    if not identifier:
        return None, "Please provide a user ID or username."

    cleaned = str(identifier).strip()
    if not cleaned:
        return None, "Please provide a user ID or username."

    if cleaned.isdigit():
        return cleaned, None

    username = cleaned.lstrip("@").strip()
    if not username:
        return None, "Please provide a user ID or username."

    record = XUser.query.filter_by(username=username).first()
    if record:
        return str(record.id), None

    response = get_x_user_by_username(username)
    if response is None:
        return None, f"Unable to resolve @{username} right now."

    payload = response if isinstance(response, dict) else None
    if payload is None:
        try:
            payload = response.json()
        except ValueError:
            payload = None

    if payload and payload.get("data", {}).get("id"):
        return str(payload["data"]["id"]), None

    return None, f"Unable to resolve @{username}. Try again or use an ID."


def resolve_x_post_id(identifier: str | None) -> tuple[str | None, str | None]:
    """Resolve a post identifier into a numeric post id."""
    if not identifier:
        return None, "Please provide a post ID."

    cleaned = str(identifier).strip()
    if not cleaned:
        return None, "Please provide a post ID."

    if cleaned.isdigit():
        return cleaned, None

    match = re.search(r"/status/(\d+)", cleaned) or re.search(r"/posts/(\d+)", cleaned)
    if match:
        return match.group(1), None

    return None, "Please provide a post ID or a post URL."


def print_x_key(payload: Mapping[str, Any], key: str) -> Any:
    """Print and return a specific key from an X API response payload."""
    value = payload.get(key)
    print(f"X API {key}: {value}")
    return value


def get_x_user_by_username(username: str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        payload = {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}
        print(payload["error"])
        return payload

    url = f"https://api.x.com/2/users/by/username/{username}"
    params = {
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        "expansions": ",".join(_filter_fields(EXPANSIONS)),
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, params=params, timeout=10)
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
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
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
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
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        _log_api_request(
            "GET",
            response.url,
            response.status_code,
            response.text,
            dict(response.headers),
            commit=True,
        )
        return response
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )

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
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
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
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
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


def get_x_users_by_ids_with_app_token(user_ids: list[str] | str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}

    if isinstance(user_ids, str):
        user_ids = [item.strip() for item in user_ids.split(",")]
    cleaned = [item.strip() for item in user_ids if item and item.strip()]
    if not cleaned:
        print("Provide at least one user id.")
        return None
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    params = {
        "ids": ",".join(cleaned),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        "expansions": ",".join(_filter_fields(EXPANSIONS)),
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        "https://api.x.com/2/users",
        headers=headers,
        params=params,
        timeout=10,
    )
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
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
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
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


def get_x_spaces_by_ids(space_ids: list[str] | str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}

    if isinstance(space_ids, str):
        space_ids = [item.strip() for item in space_ids.split(",")]
    cleaned = [space_id.strip() for space_id in space_ids if space_id and space_id.strip()]
    if not cleaned:
        print("Provide at least one Space ID.")
        return None
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    params = {
        "ids": ",".join(cleaned),
        "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
        "expansions": ",".join(SPACE_EXPANSIONS),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        "https://api.x.com/2/spaces",
        headers=headers,
        params=params,
        timeout=10,
    )

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if payload and payload.get("data"):
        for space_payload in payload.get("data", []) or []:
            space = _upsert_x_space(space_payload)
            if space:
                _record_space_snapshot(space, space_payload, "spaces_by_ids")
        includes = payload.get("includes", {})
        for user in includes.get("users", []) or []:
            _upsert_x_user(user)
        db.session.commit()
    return response


def get_x_spaces_by_creator_ids(user_ids: list[str] | str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}

    if isinstance(user_ids, str):
        user_ids = [item.strip() for item in user_ids.split(",")]
    cleaned = [user_id.strip() for user_id in user_ids if user_id and user_id.strip()]
    if not cleaned:
        print("Provide at least one user id.")
        return None
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    params = {
        "user_ids": ",".join(cleaned),
        "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
        "expansions": ",".join(SPACE_EXPANSIONS),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        "https://api.x.com/2/spaces/by/creator_ids",
        headers=headers,
        params=params,
        timeout=10,
    )

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if payload and payload.get("data"):
        for space_payload in payload.get("data", []) or []:
            space = _upsert_x_space(space_payload)
            if space:
                _record_space_snapshot(space, space_payload, "spaces_by_creator_ids")
        includes = payload.get("includes", {})
        for user in includes.get("users", []) or []:
            _upsert_x_user(user)
        db.session.commit()
    return response


def get_x_spaces_search(query: str, state: str = "all", max_results: int = 100, next_token: str | None = None) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}

    if not query:
        print("Provide a search query.")
        return None

    params = {
        "query": query,
        "state": state or "all",
        "max_results": max_results,
        "space.fields": ",".join(_filter_fields(SPACE_FIELDS)),
        "expansions": ",".join(SPACE_EXPANSIONS),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
    }
    if next_token:
        params["next_token"] = next_token

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        "https://api.x.com/2/spaces/search",
        headers=headers,
        params=params,
        timeout=10,
    )

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if payload and payload.get("data"):
        for space_payload in payload.get("data", []) or []:
            space = _upsert_x_space(space_payload)
            if space:
                _record_space_snapshot(space, space_payload, "spaces_search")
        includes = payload.get("includes", {})
        for user in includes.get("users", []) or []:
            _upsert_x_user(user)
        db.session.commit()
    return response


def get_x_space_posts(space_id: str, max_results: int = 100) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}

    cleaned = str(space_id).strip()
    if not cleaned:
        print("Provide a Space ID.")
        return None

    params = {
        "max_results": max_results,
        "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
        "expansions": ",".join(_filter_fields(TWEET_EXPANSIONS)),
        "user.fields": ",".join(_filter_fields(USER_FIELDS)),
    }

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"https://api.x.com/2/spaces/{cleaned}/tweets",
        headers=headers,
        params=params,
        timeout=10,
    )

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if payload and payload.get("data"):
        for post in payload.get("data", []) or []:
            _upsert_x_post(post)
        includes = payload.get("includes", {})
        for user in includes.get("users", []) or []:
            _upsert_x_user(user)
        db.session.commit()
    return response


def _get_active_x_user_id() -> str | None:
    token_info = get_current_user_token()
    if not token_info:
        return None
    return token_info.get("x_user_id")


def get_x_muted_users(max_results: int = 100, pagination_token: str | None = None) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "GET",
            "https://api.x.com/2/users/<ME>/muting",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/users/{x_user_id}/muting",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/users/{x_user_id}/muting",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def mute_x_user(target_user_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "POST",
            "https://api.x.com/2/users/me/muting",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.post,
        f"https://api.x.com/2/users/{x_user_id}/muting",
        json={"target_user_id": str(target_user_id)},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            f"https://api.x.com/2/users/{x_user_id}/muting",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def unmute_x_user(target_user_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "DELETE",
            "https://api.x.com/2/users/me/muting",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.delete,
        f"https://api.x.com/2/users/{x_user_id}/muting/{target_user_id}",
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "DELETE",
            f"https://api.x.com/2/users/{x_user_id}/muting/{target_user_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "DELETE",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def get_x_liked_posts(user_id: str, max_results: int = 100, pagination_token: str | None = None) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/users/{user_id}/liked_tweets",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/users/{user_id}/liked_tweets",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for post in payload.get("data", []) or []:
        _upsert_x_post(post)

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_liking_users(
    post_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/tweets/{post_id}/liking_users",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/tweets/{post_id}/liking_users",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def like_x_post(post_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "POST",
            "https://api.x.com/2/users/me/likes",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.post,
        f"https://api.x.com/2/users/{x_user_id}/likes",
        json={"tweet_id": str(post_id)},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            f"https://api.x.com/2/users/{x_user_id}/likes",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def unlike_x_post(post_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "DELETE",
            "https://api.x.com/2/users/me/likes",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.delete,
        f"https://api.x.com/2/users/{x_user_id}/likes/{post_id}",
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "DELETE",
            f"https://api.x.com/2/users/{x_user_id}/likes/{post_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "DELETE",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def get_x_community_by_id(community_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/communities/{community_id}",
        params={"community.fields": ",".join(_filter_fields(COMMUNITY_FIELDS))},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/communities/{community_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def search_x_communities(
    query: str,
    max_results: int = 10,
    next_token: str | None = None,
    pagination_token: str | None = None,
) -> Any:
    params = {
        "query": query,
        "max_results": max_results,
        "community.fields": ",".join(_filter_fields(COMMUNITY_FIELDS)),
    }
    if next_token:
        params["next_token"] = next_token
    if pagination_token:
        params["pagination_token"] = pagination_token

    response = call_x_api_with_refresh(
        requests.get,
        "https://api.x.com/2/communities/search",
        params=params,
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            "https://api.x.com/2/communities/search",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_trends_by_woeid(woeid: int, max_trends: int = 20) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN; update .env or app_vars before calling.")
        return None

    response = requests.get(
        f"https://api.x.com/2/trends/by/woeid/{woeid}",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "max_trends": max_trends,
            "trend.fields": ",".join(_filter_fields(TREND_FIELDS)),
        },
        timeout=10,
    )

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    _store_trend_snapshots(payload.get("data", []) or [], "woeid", woeid=woeid)
    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_personalized_trends() -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        "https://api.x.com/2/users/personalized_trends",
        params={
            "personalized_trend.fields": ",".join(_filter_fields(PERSONALIZED_TREND_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            "https://api.x.com/2/users/personalized_trends",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    _store_trend_snapshots(payload.get("data", []) or [], "personalized", woeid=None)
    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_news_by_id(news_id: str) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        payload = {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}
        print(payload["error"])
        return payload

    response = requests.get(
        f"https://api.x.com/2/news/{news_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"news.fields": ",".join(_filter_fields(NEWS_FIELDS))},
        timeout=10,
    )
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    _store_news_snapshots([payload["data"]], "id")
    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def search_x_news(
    query: str,
    max_results: int = 10,
    max_age_hours: int = 168,
) -> Any:
    token = get_app_var("X_BEARER_TOKEN")
    if not token:
        payload = {"error": "Missing X_BEARER_TOKEN; update .env or app_vars before calling."}
        print(payload["error"])
        return payload

    response = requests.get(
        "https://api.x.com/2/news/search",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "query": query,
            "max_results": max_results,
            "max_age_hours": max_age_hours,
            "news.fields": ",".join(_filter_fields(NEWS_FIELDS)),
        },
        timeout=10,
    )
    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    _store_news_snapshots(payload.get("data", []) or [], "search")
    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_list_by_id(list_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/lists/{list_id}",
        params={
            "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
            "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/lists/{list_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    includes = payload.get("includes", {})
    for user in includes.get("users", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_user_followed_lists(
    user_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/users/{user_id}/followed_lists",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
            "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/users/{user_id}/followed_lists",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    includes = payload.get("includes", {})
    for user in includes.get("users", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_user_owned_lists(
    user_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/users/{user_id}/owned_lists",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
            "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/users/{user_id}/owned_lists",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    includes = payload.get("includes", {})
    for user in includes.get("users", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_user_list_memberships(
    user_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/users/{user_id}/list_memberships",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
            "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/users/{user_id}/list_memberships",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    includes = payload.get("includes", {})
    for user in includes.get("users", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_list_tweets(
    list_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/lists/{list_id}/tweets",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "tweet.fields": ",".join(_filter_fields(TWEET_FIELDS)),
            "expansions": ",".join(_filter_fields(TWEET_EXPANSIONS)),
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/lists/{list_id}/tweets",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for post in payload.get("data", []) or []:
        _upsert_x_post(post)

    includes = payload.get("includes", {})
    for post in includes.get("tweets", []) or []:
        _upsert_x_post(post)
    for user in includes.get("users", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_list_followers(
    list_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/lists/{list_id}/followers",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/lists/{list_id}/followers",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def get_x_list_members(
    list_id: str,
    max_results: int = 100,
    pagination_token: str | None = None,
) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/lists/{list_id}/members",
        params={
            "max_results": max_results,
            "pagination_token": pagination_token,
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/lists/{list_id}/members",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    for user in payload.get("data", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def create_x_list(name: str, description: str | None = None, private: bool = False) -> Any:
    payload = {"name": name}
    if description:
        payload["description"] = description
    payload["private"] = bool(private)

    response = call_x_api_with_refresh(
        requests.post,
        "https://api.x.com/2/lists",
        json=payload,
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            "https://api.x.com/2/lists",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def update_x_list(
    list_id: str,
    name: str | None = None,
    description: str | None = None,
    private: bool | None = None,
) -> Any:
    payload = {}
    if name:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    if private is not None:
        payload["private"] = bool(private)

    response = call_x_api_with_refresh(
        requests.put,
        f"https://api.x.com/2/lists/{list_id}",
        json=payload,
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "PUT",
            f"https://api.x.com/2/lists/{list_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "PUT",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def delete_x_list(list_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.delete,
        f"https://api.x.com/2/lists/{list_id}",
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "DELETE",
            f"https://api.x.com/2/lists/{list_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "DELETE",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def follow_x_list(list_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "POST",
            "https://api.x.com/2/users/me/followed_lists",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.post,
        f"https://api.x.com/2/users/{x_user_id}/followed_lists",
        json={"list_id": str(list_id)},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            f"https://api.x.com/2/users/{x_user_id}/followed_lists",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def unfollow_x_list(list_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "DELETE",
            "https://api.x.com/2/users/me/followed_lists",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.delete,
        f"https://api.x.com/2/users/{x_user_id}/followed_lists/{list_id}",
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "DELETE",
            f"https://api.x.com/2/users/{x_user_id}/followed_lists/{list_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "DELETE",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def add_x_list_member(list_id: str, user_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.post,
        f"https://api.x.com/2/lists/{list_id}/members",
        json={"user_id": str(user_id)},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            f"https://api.x.com/2/lists/{list_id}/members",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def remove_x_list_member(list_id: str, user_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.delete,
        f"https://api.x.com/2/lists/{list_id}/members/{user_id}",
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "DELETE",
            f"https://api.x.com/2/lists/{list_id}/members/{user_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "DELETE",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def get_x_user_pinned_lists(user_id: str) -> Any:
    response = call_x_api_with_refresh(
        requests.get,
        f"https://api.x.com/2/users/{user_id}/pinned_lists",
        params={
            "list.fields": ",".join(_filter_fields(LIST_FIELDS)),
            "expansions": ",".join(_filter_fields(LIST_EXPANSIONS)),
            "user.fields": ",".join(_filter_fields(USER_FIELDS)),
        },
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "GET",
            f"https://api.x.com/2/users/{user_id}/pinned_lists",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "GET",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
    if not payload or "data" not in payload:
        print(response.text)
        db.session.commit()
        return response

    includes = payload.get("includes", {})
    for user in includes.get("users", []) or []:
        _upsert_x_user(user)

    db.session.commit()

    print(json.dumps(payload, indent=4))
    return response


def pin_x_list(list_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "POST",
            "https://api.x.com/2/users/me/pinned_lists",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.post,
        f"https://api.x.com/2/users/{x_user_id}/pinned_lists",
        json={"list_id": str(list_id)},
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "POST",
            f"https://api.x.com/2/users/{x_user_id}/pinned_lists",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "POST",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response


def unpin_x_list(list_id: str) -> Any:
    x_user_id = _get_active_x_user_id()
    if not x_user_id:
        payload = {"error": "No active X account available."}
        _log_api_request(
            "DELETE",
            "https://api.x.com/2/users/me/pinned_lists",
            None,
            json.dumps(payload),
            None,
            commit=True,
        )
        print(json.dumps(payload, indent=4))
        return payload

    response = call_x_api_with_refresh(
        requests.delete,
        f"https://api.x.com/2/users/{x_user_id}/pinned_lists/{list_id}",
        timeout=10,
    )
    if isinstance(response, dict):
        _log_api_request(
            "DELETE",
            f"https://api.x.com/2/users/{x_user_id}/pinned_lists/{list_id}",
            None,
            json.dumps(response),
            None,
            commit=True,
        )
        print(json.dumps(response, indent=4))
        return response

    _log_api_request(
        "DELETE",
        response.url,
        response.status_code,
        response.text,
        dict(response.headers),
    )
    print(response.text)
    db.session.commit()
    return response
