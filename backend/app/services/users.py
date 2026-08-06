from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.schemas.auth import RegisterRequest


class UserAlreadyExistsError(Exception):
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
