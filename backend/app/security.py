"""Token based authentication and role/ownership authorisation.

Tokens are configured by the operator through ``EVALFORGE_API_KEYS``
("token:user_id:role" entries). Nothing is hard-coded; when no keys are
configured every protected endpoint fails closed unless the app runs in
development with ``AUTH_DISABLED=true``.
"""
import hmac
from dataclasses import dataclass
from typing import List, Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class User:
    id: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _configured_users() -> List[tuple]:
    entries = []
    for raw in settings.EVALFORGE_API_KEYS.split(","):
        parts = [p.strip() for p in raw.strip().split(":")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        role = parts[2] if len(parts) > 2 and parts[2] in ("admin", "user") else "user"
        entries.append((parts[0], User(id=parts[1], role=role)))
    return entries


def authenticate_token(token: str) -> Optional[User]:
    found: Optional[User] = None
    for candidate, user in _configured_users():
        # compare every entry to keep timing independent of which entry matches
        if hmac.compare_digest(candidate.encode(), token.encode()):
            found = user
    return found


def get_current_user(authorization: Optional[str] = Header(default=None)) -> User:
    if settings.AUTH_DISABLED and settings.APP_ENV == "development":
        return User(id="dev-user", role="admin")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    user = authenticate_token(authorization[7:].strip())
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user


def assert_owner(user: User, owner_id: Optional[str]) -> None:
    """Owners and administrators may access a resource; everyone else gets 404
    (not 403) so that resource existence is not disclosed."""
    if user.is_admin or owner_id == user.id:
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
