import base64
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import dotenv_values
from flask import current_app, has_app_context

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.extensions import db
from app.models import AppVar


def load_env_vars_to_db() -> int:
    """Sync .env values into the app_vars table on app startup."""
    env_path = Path(current_app.root_path).parent / ".env"
    if not env_path.exists():
        return 0

    values: Mapping[str, Optional[str]] = dotenv_values(env_path)
    try:
        existing = {row.key: row for row in AppVar.query.all()}
    except Exception:
        db.session.rollback()
        return 0

    for key, value in values.items():
        record = existing.pop(key, None)
        if record is None:
            record = AppVar(key=key, value=value)
            db.session.add(record)
        else:
            record.value = value

    for record in existing.values():
        db.session.delete(record)

    db.session.commit()
    return len(values)


def get_app_var(key: str, default: Optional[Any] = None) -> Optional[Any]:
    """Fetch a value from app_vars with safe fallbacks."""
    if has_app_context():
        try:
            record = AppVar.query.filter_by(key=key).first()
            if record is not None:
                return record.value
        except Exception:
            pass
        return current_app.config.get(key, os.getenv(key, default))

    return os.getenv(key, default)


def _derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _get_key() -> bytes:
    raw = get_app_var("X_TOKEN_ENCRYPTION_KEY") or get_app_var("SECRET_KEY", "dev-secret")
    return _derive_key(raw)


def encrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("utf-8")


def decrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    key = _get_key()
    aesgcm = AESGCM(key)
    payload = base64.urlsafe_b64decode(value.encode("utf-8"))
    nonce = payload[:12]
    ciphertext = payload[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
