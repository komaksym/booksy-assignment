from fastapi import FastAPI
from tinydb import Query

from hardware_hub.auth import create_user
from hardware_hub.inventory import create_hardware


def _login(client, email: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _asset_id(record: dict[str, object]) -> str:
    internal_id = str(record["id"])
    return f"HH-{internal_id[:8].upper()}-{internal_id[9:13].upper()}"


def test_inventory_separates_public_asset_identity_from_import_provenance(
    client, app: FastAPI
) -> None:
    imported = app.state.hardware.get(Query().source_id == 1)
    assert imported is not None
    manual = create_hardware(
        app.state.hardware,
        {
            "name": "Manual computer",
            "brand": "Dell",
            "purchase_date": "2026-07-23",
            "status": "Available",
            "notes": "",
            "legacy_history": "",
        },
    )

    _login(client, "admin@booksy.test", "admin-password")
    admin = client.get("/")

    assert admin.status_code == 200
    assert "Origin / Source ID" in admin.text
    assert "Imported · #1" in admin.text
    assert "Manual entry" in admin.text
    assert f"Asset ID {_asset_id(imported)}" in admin.text
    assert f"Asset ID {_asset_id(manual)}" in admin.text

    client.post("/logout", follow_redirects=False)
    ordinary = create_user(app.state.users, "viewer@booksy.test", "user-password")
    _login(client, str(ordinary["email"]), "user-password")
    dashboard = client.get("/")

    assert dashboard.status_code == 200
    assert "Origin / Source ID" not in dashboard.text
    assert "Imported · #1" not in dashboard.text
    assert "Manual entry" not in dashboard.text
    assert f"Asset ID {_asset_id(imported)}" in dashboard.text
    assert f"Asset ID {_asset_id(manual)}" in dashboard.text


def test_detail_localizes_history_while_preserving_exact_utc(client, app: FastAPI) -> None:
    viewer = create_user(app.state.users, "history@booksy.test", "user-password")
    imported = app.state.hardware.get(Query().source_id == 1)
    assert imported is not None
    timestamp = "2026-07-23T00:44:55.385815+00:00"
    app.state.hardware.update(
        {"rental_history": [{"type": "rent", "user_id": viewer["id"], "occurred_at": timestamp}]},
        Query().id == imported["id"],
    )
    _login(client, str(viewer["email"]), "user-password")

    detail = client.get(f"/hardware/{imported['id']}")

    assert detail.status_code == 200
    assert f"<dt>Asset ID</dt><dd>{_asset_id(imported)}</dd>" in detail.text
    assert f'datetime="{timestamp}" data-local-datetime' in detail.text
    assert "2026-07-23 00:44 UTC" in detail.text
    assert f">{timestamp}</time>" not in detail.text
    assert "Intl.DateTimeFormat" in detail.text
    assert "date.toISOString()" in detail.text
