import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.blueprints.auth import oauth
from app.blueprints.auth.decorators import login_required
from app.blueprints.auth.oauth_flow import handle_callback
from app.extensions import db
from app.models import User, UserLinkedAccount, UserOAuthToken

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username == "admin" and password == "admin":
            user = User.query.filter_by(username="admin").first()
            if not user:
                user = User(username="admin", name="Admin", is_admin=True)
                db.session.add(user)
                db.session.commit()
            session["user_id"] = user.id
            flash("Logged in as admin.", "success")
            return redirect(url_for("home.index"))
        flash("Invalid credentials.", "danger")
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home.index"))


@bp.route("/x-login")
def x_login():
    if not current_app.config.get("X_CLIENT_ID") or not current_app.config.get("X_CLIENT_SECRET"):
        flash("X OAuth is not configured. Set X_CLIENT_ID and X_CLIENT_SECRET.", "danger")
        return redirect(url_for("home.index"))
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = oauth.generate_pkce_pair()
    redirect_uri = current_app.config.get("X_REDIRECT_URI") or url_for(
        "auth.callback", _external=True
    )

    session["oauth_state"] = state
    session["oauth_code_verifier"] = code_verifier
    session["oauth_redirect_uri"] = redirect_uri

    auth_url = oauth.build_authorize_url(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )
    return redirect(auth_url)


@bp.route("/x-connect")
@login_required
def x_connect():
    session["linking_owner_user_id"] = session["user_id"]
    return redirect(url_for("auth.x_login"))


@bp.route("/x-accounts/<int:account_id>/reauth")
@login_required
def reauth(account_id):
    linked = UserLinkedAccount.query.filter_by(id=account_id, owner_user_id=session["user_id"]).first()
    if not linked:
        flash("Linked account not found.", "danger")
        return redirect(url_for("home.index"))
    session["linking_owner_user_id"] = session["user_id"]
    return redirect(url_for("auth.x_login"))


@bp.route("/callback")
@bp.route("/auth/callback")
def callback():
    return handle_callback(
        code=request.args.get("code"),
        state=request.args.get("state"),
        expected_state=session.get("oauth_state"),
        code_verifier=session.get("oauth_code_verifier"),
        redirect_uri=session.get("oauth_redirect_uri"),
    )


@bp.route("/x-accounts/<int:account_id>/activate", methods=["POST"])
@login_required
def activate_account(account_id):
    linked = UserLinkedAccount.query.filter_by(id=account_id, owner_user_id=session["user_id"]).first()
    if not linked:
        flash("Linked account not found.", "danger")
        return redirect(url_for("home.index"))
    session["active_x_user_id"] = linked.x_user_id
    flash("Active X account updated.", "success")
    return redirect(url_for("home.index"))


@bp.route("/x-accounts/<int:account_id>/disconnect", methods=["POST"])
@login_required
def disconnect_account(account_id):
    linked = UserLinkedAccount.query.filter_by(id=account_id, owner_user_id=session["user_id"]).first()
    if not linked:
        flash("Linked account not found.", "danger")
        return redirect(url_for("home.index"))
    UserOAuthToken.query.filter_by(
        owner_user_id=session["user_id"], x_user_id=linked.x_user_id
    ).delete()
    db.session.delete(linked)
    db.session.commit()
    if session.get("active_x_user_id") == linked.x_user_id:
        session.pop("active_x_user_id", None)
    flash("Linked account removed.", "info")
    return redirect(url_for("home.index"))


@bp.route("/x-accounts/<int:account_id>/refresh-token", methods=["POST"])
@login_required
def refresh_token(account_id):
    linked = UserLinkedAccount.query.filter_by(id=account_id, owner_user_id=session["user_id"]).first()
    if not linked:
        flash("Linked account not found.", "danger")
        return redirect(url_for("home.index"))
    token = UserOAuthToken.query.filter_by(
        owner_user_id=session["user_id"], x_user_id=linked.x_user_id
    ).first()
    if not token:
        flash("No token for this account.", "warning")
        return redirect(url_for("home.index"))
    session["active_x_user_id"] = linked.x_user_id
    flash("Token refresh scheduled on next API call.", "info")
    return redirect(url_for("home.index"))


@bp.route("/x-accounts/<int:account_id>/revoke-token", methods=["POST"])
@login_required
def revoke_token(account_id):
    linked = UserLinkedAccount.query.filter_by(id=account_id, owner_user_id=session["user_id"]).first()
    if not linked:
        flash("Linked account not found.", "danger")
        return redirect(url_for("home.index"))
    UserOAuthToken.query.filter_by(
        owner_user_id=session["user_id"], x_user_id=linked.x_user_id
    ).delete()
    db.session.commit()
    flash("Token revoked.", "info")
    return redirect(url_for("home.index"))
