from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()

JWT_ALGORITHM = "HS256"


class InvalidAccessTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
    if not subject or not subject.strip():
        raise ValueError("subject must be a non-empty string")

    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.InvalidTokenError as exc:
        raise InvalidAccessTokenError from exc

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise InvalidAccessTokenError

    return sub
