from datetime import datetime

from flask import session

from app.blueprints.auth import oauth
from app.extensions import db
from app.models import UserOAuthToken
from app.utils.encrypt_decrypt import decrypt_value, encrypt_value


def _is_expired(expires_at):
    if not expires_at:
        return False
    return datetime.utcnow() >= expires_at


def store_tokens(owner_user_id, x_user_id, token_data):
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_at = token_data.get("expires_at")
    scope = token_data.get("scope")

    record = UserOAuthToken.query.filter_by(
        owner_user_id=owner_user_id, x_user_id=x_user_id
    ).first()
    if not record:
        record = UserOAuthToken(owner_user_id=owner_user_id, x_user_id=x_user_id)
        db.session.add(record)

    record.access_token = encrypt_value(access_token)
    record.refresh_token = encrypt_value(refresh_token) if refresh_token else record.refresh_token
    record.expires_at = expires_at
    if scope:
        record.scope = scope
    db.session.commit()
    return record


def get_current_user_token():
    owner_user_id = session.get("user_id")
    if not owner_user_id:
        return None
    active_x_user_id = session.get("active_x_user_id")
    token = None
    if active_x_user_id:
        token = UserOAuthToken.query.filter_by(
            owner_user_id=owner_user_id, x_user_id=active_x_user_id
        ).first()
    if not token:
        token = UserOAuthToken.query.filter_by(owner_user_id=owner_user_id).first()
    if not token:
        return None

    access_token = decrypt_value(token.access_token)
    refresh_token = decrypt_value(token.refresh_token)

    if refresh_token and _is_expired(token.expires_at):
        refreshed = oauth.refresh_tokens(refresh_token)
        if "access_token" in refreshed:
            token = store_tokens(owner_user_id, token.x_user_id, refreshed)
            access_token = decrypt_value(token.access_token)
            refresh_token = decrypt_value(token.refresh_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "x_user_id": token.x_user_id,
    }


def call_x_api_with_refresh(request_func, url, **kwargs):
    token_info = get_current_user_token()
    if not token_info:
        return {"error": "No X account linked yet."}

    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token_info['access_token']}"
    response = request_func(url, headers=headers, **kwargs)
    if response.status_code != 401:
        return response

    refresh_token = token_info.get("refresh_token")
    if not refresh_token:
        return response

    refreshed = oauth.refresh_tokens(refresh_token)
    if "access_token" not in refreshed:
        return response

    store_tokens(session["user_id"], token_info["x_user_id"], refreshed)
    headers["Authorization"] = f"Bearer {refreshed['access_token']}"
    return request_func(url, headers=headers, **kwargs)
