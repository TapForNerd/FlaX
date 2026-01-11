from flask import current_app, flash, redirect, session, url_for

from app.blueprints.auth import oauth
from app.blueprints.auth.token_helpers import store_tokens
from app.extensions import db
from app.models import User, UserLinkedAccount


def _is_admin_username(username):
    admin_list = current_app.config.get("X_ADMIN_USERNAMES", "")
    admins = [name.strip().lower() for name in admin_list.split(",") if name.strip()]
    return username.lower() in admins if username else False


def handle_callback(code, state, expected_state, code_verifier, redirect_uri):
    if not code or state != expected_state:
        flash("Invalid OAuth response.", "danger")
        return redirect(url_for("home.index"))

    token_data = oauth.exchange_code_for_token(code, code_verifier, redirect_uri)
    if "access_token" not in token_data:
        flash("OAuth token exchange failed.", "danger")
        return redirect(url_for("home.index"))

    profile = oauth.fetch_profile(token_data["access_token"])
    user_data = profile.get("data") if isinstance(profile, dict) else None
    if not user_data:
        flash("Unable to load X profile.", "danger")
        return redirect(url_for("home.index"))

    x_user_id = user_data.get("id")
    username = user_data.get("username", "")
    name = user_data.get("name")
    profile_image = user_data.get("profile_image_url")

    owner_user_id = session.get("linking_owner_user_id") or session.get("user_id")
    if not owner_user_id:
        user = User.query.filter_by(username=username).first() if username else None
        if not user:
            safe_username = username or f"x_{x_user_id}"
            if User.query.filter_by(username=safe_username).first():
                safe_username = f"x_{x_user_id}"
            user = User(
                username=safe_username,
                name=name,
                profile_image=profile_image,
                is_admin=_is_admin_username(username),
            )
            db.session.add(user)
            db.session.commit()
        owner_user_id = user.id
        session["user_id"] = owner_user_id

    linked = UserLinkedAccount.query.filter_by(
        owner_user_id=owner_user_id, x_user_id=x_user_id
    ).first()
    if not linked:
        linked = UserLinkedAccount(
            owner_user_id=owner_user_id,
            x_user_id=x_user_id,
            username=username,
            name=name,
            profile_image=profile_image,
        )
        db.session.add(linked)
    else:
        linked.username = username
        linked.name = name
        linked.profile_image = profile_image
    db.session.commit()

    store_tokens(owner_user_id, x_user_id, token_data)
    session["active_x_user_id"] = x_user_id

    session.pop("linking_owner_user_id", None)
    session.pop("oauth_state", None)
    session.pop("oauth_code_verifier", None)
    session.pop("oauth_redirect_uri", None)

    flash("X account connected.", "success")
    return redirect(url_for("home.index"))
