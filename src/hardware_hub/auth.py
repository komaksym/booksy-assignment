"""User creation, authentication, and request authorization helpers."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import Request
from pwdlib import PasswordHash
from tinydb import Query
from tinydb.table import Table

_PASSWORDS = PasswordHash.recommended()


class UserInputError(ValueError):
    """Represent a safe validation message that can be rendered to a user."""


def normalize_email(email: str) -> str:
    """Normalize and minimally validate an email address."""

    normalized = email.strip().lower()
    if normalized.count("@") != 1:
        raise UserInputError("Enter a valid email address")
    local, domain = normalized.split("@")
    if not local or not domain:
        raise UserInputError("Enter a valid email address")
    return normalized


def validate_password(password: str) -> None:
    """Apply the MVP password-length rule."""

    if len(password) < 8:
        raise UserInputError("Password must contain at least 8 characters")


def create_user(users: Table, email: str, password: str, role: str = "user") -> dict[str, Any]:
    """Validate and insert one active user with a hashed password."""

    normalized = normalize_email(email)
    validate_password(password)
    if role not in {"admin", "user"}:
        raise ValueError("Unsupported user role")
    if users.search(Query().email == normalized):
        raise UserInputError("User already exists")

    user = {
        "id": str(uuid4()),
        "email": normalized,
        "password_hash": _PASSWORDS.hash(password),
        "role": role,
        "active": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    users.insert(user)
    return user


def bootstrap_admin(users: Table, email: str, password: str) -> None:
    """Create the first administrator once without changing existing accounts."""

    if users.search(Query().role == "admin"):
        return

    normalized = normalize_email(email)
    validate_password(password)
    if users.search(Query().email == normalized):
        raise RuntimeError("Bootstrap administrator conflicts with an existing user")
    create_user(users, normalized, password, role="admin")


def authenticate(users: Table, email: str, password: str) -> dict[str, Any] | None:
    """Return an active user when the supplied credentials match."""

    try:
        normalized = normalize_email(email)
    except UserInputError:
        return None

    matches = users.search(Query().email == normalized)
    if not matches:
        return None
    user = matches[0]
    if not user.get("active"):
        return None
    if not _PASSWORDS.verify(password, user["password_hash"]):
        return None
    return user


def current_user(request: Request) -> dict[str, Any] | None:
    """Reload the active session user from storage on every request."""

    user_id = request.session.get("user_id")
    if not isinstance(user_id, str):
        request.session.clear()
        return None

    users = request.app.state.users
    matches = users.search(Query().id == user_id)
    if not matches or not matches[0].get("active"):
        request.session.clear()
        return None
    return matches[0]
