from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import token_subject
from app.models import User

bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    subject = token_subject(credentials.credentials) if credentials else None
    if not subject:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid account")
    return user
