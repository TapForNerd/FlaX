import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from flask import current_app


def generate_pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge.rstrip(b"=").decode("utf-8")


def build_authorize_url(redirect_uri, state, code_challenge):
    scopes = [
        "tweet.read",
        "tweet.write",
        "users.read",
        "like.read",
        "like.write",
        "mute.read",
        "mute.write",
        "list.read",
        "list.write",
        "offline.access",
    ]
    params = {
        "response_type": "code",
        "client_id": current_app.config["X_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"https://x.com/i/oauth2/authorize?{urlencode(params)}"


def exchange_code_for_token(code, code_verifier, redirect_uri):
    client_id = current_app.config["X_CLIENT_ID"]
    client_secret = current_app.config.get("X_CLIENT_SECRET")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {basic}"
    response = requests.post(
        "https://api.x.com/2/oauth2/token",
        data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        headers=headers,
        timeout=10,
    )
    data = response.json()
    if "expires_in" in data:
        data["expires_at"] = datetime.utcnow() + timedelta(seconds=int(data["expires_in"]))
    return data


def refresh_tokens(refresh_token):
    client_id = current_app.config["X_CLIENT_ID"]
    client_secret = current_app.config.get("X_CLIENT_SECRET")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {basic}"
    response = requests.post(
        "https://api.x.com/2/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        headers=headers,
        timeout=10,
    )
    data = response.json()
    if "expires_in" in data:
        data["expires_at"] = datetime.utcnow() + timedelta(seconds=int(data["expires_in"]))
    return data


def fetch_profile(access_token):
    response = requests.get(
        "https://api.x.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"user.fields": "id,name,username,profile_image_url,created_at"},
        timeout=10,
    )
    return response.json()
