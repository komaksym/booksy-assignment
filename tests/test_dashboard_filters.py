from fastapi import FastAPI

from hardware_hub.auth import create_user


def _login(client, email: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_dashboard_status_choices_are_role_scoped(client, app: FastAPI) -> None:
    ordinary = create_user(app.state.users, "viewer@booksy.test", "user-password")
    _login(client, ordinary["email"], "user-password")

    response = client.get("/")

    assert response.status_code == 200
    assert response.context["status_choices"] == ("Available", "In Use", "Repair")
    assert '<option value="Needs correction"' not in response.text

    crafted = client.get("/?status=Needs%20correction")

    assert crafted.status_code == 400
    assert "Choose a supported status filter" in crafted.text
    assert crafted.context["status_choices"] == ("Available", "In Use", "Repair")
    assert '<option value="Needs correction"' not in crafted.text

    client.post("/logout", follow_redirects=False)
    _login(client, "admin@booksy.test", "admin-password")

    admin_response = client.get("/")

    assert admin_response.status_code == 200
    assert admin_response.context["status_choices"] == (
        "Available",
        "In Use",
        "Repair",
        "Needs correction",
    )
    assert '<option value="Needs correction"' in admin_response.text
