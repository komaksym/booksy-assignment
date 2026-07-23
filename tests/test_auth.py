import json
from base64 import b64decode
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from hardware_hub.config import Settings
from hardware_hub.db import users_table

_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60


def test_login_uses_relative_stylesheet_url_behind_https_proxy(
    client: TestClient,
) -> None:
    response = client.get("/login", headers={"x-forwarded-proto": "https"})

    assert response.status_code == 200
    assert 'href="/static/app.css"' in response.text
    assert 'href="http://' not in response.text


def session_payload(client: TestClient, settings: Settings) -> dict[str, str]:
    cookie = client.cookies.get("session")
    assert cookie is not None
    signed = TimestampSigner(settings.session_secret).unsign(
        cookie,
        max_age=_SESSION_MAX_AGE_SECONDS,
    )
    return json.loads(b64decode(signed))


def test_admin_creates_user_and_signed_session_enforces_roles(
    client: TestClient,
    app: FastAPI,
    settings: Settings,
) -> None:
    response = client.post(
        "/login",
        data={
            "email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users"
    assert f"Max-Age={_SESSION_MAX_AGE_SECONDS}" in response.headers["set-cookie"]
    assert set(session_payload(client, settings)) == {"user_id"}
    admin_user_id = session_payload(client, settings)["user_id"]

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers

    response = client.post(
        "/login",
        data={"email": settings.bootstrap_admin_email, "password": "wrong-password"},
    )

    assert response.status_code == 400
    assert session_payload(client, settings)["user_id"] == admin_user_id

    response = client.post(
        "/admin/users",
        data={"email": " New.User@Booksy.Test ", "password": "user-password"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users"
    users = users_table(app.state.db).all()
    assert len(users) == 2
    assert users[1]["email"] == "new.user@booksy.test"
    assert users[1]["role"] == "user"
    assert users[1]["active"] is True
    assert users[1]["password_hash"].startswith("$argon2")

    client.post("/logout", follow_redirects=False)
    response = client.post(
        "/admin/users",
        data={"email": "anonymous@booksy.test", "password": "anonymous-password"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    response = client.post(
        "/login",
        data={"email": "new.user@booksy.test", "password": "user-password"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    response = client.post(
        "/admin/users",
        data={"email": "blocked@booksy.test", "password": "blocked-password"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert len(users_table(app.state.db).all()) == 2


def test_short_session_secret_fails_without_echoing_secret(tmp_path: Path) -> None:
    from hardware_hub.app import create_app

    secret = "too-short"
    settings = Settings(
        environment="test",
        tinydb_path=tmp_path / "hardware-hub.json",
        session_secret=secret,
        bootstrap_admin_email="admin@booksy.test",
        bootstrap_admin_password="admin-password",
    )

    with pytest.raises(RuntimeError) as exc_info:
        create_app(settings)

    message = str(exc_info.value)
    assert "SESSION_SECRET" in message
    assert secret not in message
