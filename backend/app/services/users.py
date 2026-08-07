from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest


class UserAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_user(db: Session, payload: RegisterRequest) -> User:
    normalized_email = str(payload.email).strip().lower()

    existing = db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise UserAlreadyExistsError

    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    normalized_email = email.strip().lower()

    user = db.scalar(select(User).where(User.email == normalized_email))

    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError

    return user
