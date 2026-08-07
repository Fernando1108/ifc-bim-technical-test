from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import InvalidAccessTokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        subject = decode_access_token(token)
        user_id = int(subject)
        if user_id <= 0:
            raise ValueError("user_id must be positive")
    except (InvalidAccessTokenError, ValueError):
        raise _credentials_exception() from None

    user = db.scalar(select(User).where(User.id == user_id))

    if user is None:
        raise _credentials_exception()

    if not user.is_active:
        raise _credentials_exception()

    return user
