from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from tinydb import Query

from hardware_hub.auth import create_user
from hardware_hub.inventory import InventoryConflictError, update_hardware
from hardware_hub.rules import find_issues


def _login(client, email: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _edit_form(
    record: dict[str, object], *, status: str, name: str | None = None
) -> dict[str, str]:
    return {
        "name": name or str(record["name"]),
        "brand": str(record.get("brand") or ""),
        "purchase_date": str(record.get("purchase_date") or ""),
        "status": status,
        "notes": str(record.get("notes") or ""),
        "legacy_history": str(record.get("legacy_history") or ""),
    }


@pytest.mark.parametrize("target_status", ["Available", "Repair"])
def test_admin_edit_releases_held_item_with_one_coherent_update(
    client, app: FastAPI, monkeypatch: pytest.MonkeyPatch, target_status: str
) -> None:
    hardware = app.state.hardware
    holder = create_user(app.state.users, "holder@booksy.test", "user-password")
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None

    _login(client, holder["email"], "user-password")
    assert (
        client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False).status_code == 303
    )
    held = hardware.get(Query().id == source_one["id"])
    assert held is not None

    client.post("/logout", follow_redirects=False)
    _login(client, "admin@booksy.test", "admin-password")
    administrator = app.state.users.get(Query().email == "admin@booksy.test")
    assert administrator is not None
    submitted = _edit_form(held, status=target_status, name="Released inventory item")
    submitted.update(
        {
            "brand": "Framework",
            "purchase_date": "2024-01-15",
            "notes": "Released by inventory administration.",
            "legacy_history": "Administrative release recorded.",
        }
    )
    updates: list[dict[str, object]] = []
    original_update = hardware.update

    def capture_update(fields, *args, **kwargs):
        updates.append(deepcopy(fields))
        return original_update(fields, *args, **kwargs)

    monkeypatch.setattr(hardware, "update", capture_update)
    response = client.post(
        f"/admin/hardware/{source_one['id']}/edit",
        data=submitted,
        follow_redirects=False,
    )

    assert response.status_code == 303
    released = hardware.get(Query().id == source_one["id"])
    assert released is not None
    assert len(updates) == 1
    assert updates[0] == released
    assert released["name"] == submitted["name"]
    assert released["brand"] == submitted["brand"]
    assert released["purchase_date"] == submitted["purchase_date"]
    assert released["notes"] == submitted["notes"]
    assert released["legacy_history"] == submitted["legacy_history"]
    assert released["status"] == target_status
    assert released["holder_user_id"] is None
    assert released["rental_history"][:-1] == held["rental_history"]
    event = released["rental_history"][-1]
    assert set(event) == {"type", "user_id", "target_status", "occurred_at"}
    assert event["type"] == "admin_release"
    assert event["user_id"] == administrator["id"]
    assert event["target_status"] == target_status
    assert datetime.fromisoformat(event["occurred_at"]).utcoffset() == timedelta(0)
    assert released["updated_at"] == event["occurred_at"]
    assert released["raw_payload"] == held["raw_payload"]


def test_admin_metadata_edit_keeps_held_item_and_history(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    holder = create_user(app.state.users, "holder@booksy.test", "user-password")
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None

    _login(client, holder["email"], "user-password")
    assert (
        client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False).status_code == 303
    )
    held = hardware.get(Query().id == source_one["id"])
    assert held is not None

    client.post("/logout", follow_redirects=False)
    _login(client, "admin@booksy.test", "admin-password")
    response = client.post(
        f"/admin/hardware/{source_one['id']}/edit",
        data=_edit_form(held, status="Keep current", name="Metadata-only change"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    edited = hardware.get(Query().id == source_one["id"])
    assert edited is not None
    assert edited["name"] == "Metadata-only change"
    assert edited["status"] == "In Use"
    assert edited["holder_user_id"] == holder["id"]
    assert edited["rental_history"] == held["rental_history"]


def test_held_edit_page_hides_delete_form_and_explains_why(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    holder = create_user(app.state.users, "holder@booksy.test", "user-password")
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None

    _login(client, holder["email"], "user-password")
    assert (
        client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False).status_code == 303
    )
    client.post("/logout", follow_redirects=False)
    _login(client, "admin@booksy.test", "admin-password")

    response = client.get(f"/admin/hardware/{source_one['id']}/edit")

    assert response.status_code == 200
    assert (
        f'<form method="post" action="/admin/hardware/{source_one["id"]}/delete">'
        not in response.text
    )
    assert "This item cannot be deleted while it has a holder." in response.text


def test_admin_release_history_has_semantic_label_target_and_no_raw_uuid(
    client, app: FastAPI
) -> None:
    hardware = app.state.hardware
    administrator = app.state.users.get(Query().email == "admin@booksy.test")
    source_one = hardware.get(Query().source_id == 1)
    assert administrator is not None
    assert source_one is not None
    event = {
        "type": "admin_release",
        "user_id": administrator["id"],
        "target_status": "Repair",
        "occurred_at": "2026-07-22T12:00:00+00:00",
    }
    hardware.update({"rental_history": [event]}, Query().id == source_one["id"])
    _login(client, administrator["email"], "admin-password")

    response = client.get(f"/hardware/{source_one['id']}")

    assert response.status_code == 200
    assert "Administrator release to Repair" in response.text
    assert administrator["email"] in response.text
    assert administrator["id"] not in response.text


def test_admin_release_rejects_malformed_rental_history_without_writing(
    client, app: FastAPI
) -> None:
    hardware = app.state.hardware
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None
    malformed = deepcopy(source_one)
    malformed.update({"status": "In Use", "holder_user_id": "holder-id", "rental_history": {}})
    hardware.update(malformed, Query().id == source_one["id"])
    before = hardware.get(Query().id == source_one["id"])
    assert before is not None

    with pytest.raises(InventoryConflictError, match="rental history is invalid"):
        update_hardware(
            hardware,
            str(source_one["id"]),
            _edit_form(before, status="Available"),
            acting_user_id="admin-id",
        )

    assert hardware.get(Query().id == source_one["id"]) == before


def test_update_hardware_keeps_legacy_normal_edit_call_shape(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None

    updated = update_hardware(
        hardware,
        str(source_one["id"]),
        _edit_form(source_one, status="Keep current", name="Compatible edit"),
    )

    assert updated is not None
    assert updated["name"] == "Compatible edit"


def test_admin_release_requires_an_actor_without_writing(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None
    held = deepcopy(source_one)
    held.update({"status": "In Use", "holder_user_id": "holder-id"})
    hardware.update(held, Query().id == source_one["id"])
    before = hardware.get(Query().id == source_one["id"])
    assert before is not None

    with pytest.raises(InventoryConflictError, match="Administrator identity is required"):
        update_hardware(hardware, str(source_one["id"]), _edit_form(before, status="Available"))

    assert hardware.get(Query().id == source_one["id"]) == before


def test_admin_edit_error_renders_the_current_record_after_service_failure(
    client, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hardware_hub.app as app_module

    hardware = app.state.hardware
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None
    _login(client, "admin@booksy.test", "admin-password")

    def fail_after_concurrent_change(*args, **kwargs):
        current = hardware.get(Query().id == source_one["id"])
        assert current is not None
        current["status"] = "In Use"
        current["holder_user_id"] = "another-user"
        hardware.update(current, Query().id == source_one["id"])
        raise InventoryConflictError("Status cannot change while hardware has a holder")

    monkeypatch.setattr(app_module, "update_hardware", fail_after_concurrent_change)
    response = client.post(
        f"/admin/hardware/{source_one['id']}/edit",
        data=_edit_form(source_one, status="Repair"),
        follow_redirects=False,
    )

    assert response.status_code == 409
    assert "Current: In Use" in response.text
    assert f'action="/admin/hardware/{source_one["id"]}/delete"' not in response.text
    assert "This item cannot be deleted while it has a holder." in response.text


def test_admin_edit_error_returns_not_found_if_record_disappears_during_service_failure(
    client, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hardware_hub.app as app_module

    hardware = app.state.hardware
    source_one = hardware.get(Query().source_id == 1)
    assert source_one is not None
    _login(client, "admin@booksy.test", "admin-password")

    def fail_after_concurrent_delete(*args, **kwargs):
        hardware.remove(Query().id == source_one["id"])
        raise InventoryConflictError("Status cannot change while hardware has a holder")

    monkeypatch.setattr(app_module, "update_hardware", fail_after_concurrent_delete)
    response = client.post(
        f"/admin/hardware/{source_one['id']}/edit",
        data=_edit_form(source_one, status="Repair"),
        follow_redirects=False,
    )

    assert response.status_code == 404


def test_delete_context_is_derived_in_python() -> None:
    from hardware_hub.app import _hardware_form_context

    user = {"id": "admin-id", "role": "admin"}
    held = _hardware_form_context(
        user=user,
        record={"id": "hardware-id", "holder_user_id": "holder-id", "status": "In Use"},
        values={},
        error=None,
    )
    available = _hardware_form_context(
        user=user,
        record={"id": "hardware-id", "holder_user_id": None, "status": "Available"},
        values={},
        error=None,
    )

    assert held["delete_action"] is None
    assert held["delete_reason"] == "This item cannot be deleted while it has a holder."
    assert available["delete_action"] == "delete"
    assert available["delete_reason"] is None


def test_admin_inventory_writes_preserve_raw_evidence(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    source_ten = hardware.get(Query().source_id == 10)
    assert source_ten is not None
    source_six = hardware.get(Query().source_id == 6)
    assert source_six is not None

    internal_id = source_ten["id"]
    raw_payload = deepcopy(source_ten["raw_payload"])
    initial_count = len(hardware)
    initial_findings = find_issues(hardware.all(), date(2026, 7, 22))
    assert {finding.code for finding in initial_findings if finding.source_id == 10} == {
        "MISSING_BRAND",
        "MISSING_PURCHASE_DATE",
        "INVALID_STATUS",
    }

    create_user(app.state.users, "ordinary@booksy.test", "user-password")
    client.post(
        "/login",
        data={"email": "ordinary@booksy.test", "password": "user-password"},
        follow_redirects=False,
    )
    response = client.post(
        f"/admin/hardware/{internal_id}/edit",
        data={
            "name": "Unknown Device",
            "brand": "Framework",
            "purchase_date": "2024-01-15",
            "status": "Available",
            "notes": "",
            "legacy_history": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert hardware.get(Query().id == internal_id) == source_ten

    client.post("/logout", follow_redirects=False)
    client.post(
        "/login",
        data={"email": "admin@booksy.test", "password": "admin-password"},
        follow_redirects=False,
    )
    response = client.post(
        f"/admin/hardware/{internal_id}/edit",
        data={
            "name": "Unknown Device",
            "brand": "Framework",
            "purchase_date": "2024-01-15",
            "status": "Available",
            "notes": "",
            "legacy_history": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    corrected = hardware.get(Query().id == internal_id)
    assert corrected is not None
    assert corrected["id"] == internal_id
    assert corrected["brand"] == "Framework"
    assert corrected["purchase_date"] == "2024-01-15"
    assert corrected["status"] == "Available"
    assert (
        corrected["raw_payload"]
        == raw_payload
        == {
            "id": 10,
            "name": "Unknown Device",
            "brand": "",
            "purchaseDate": None,
            "status": "Unknown",
        }
    )
    assert len(hardware) == initial_count

    remaining = find_issues(hardware.all(), date(2026, 7, 22))
    assert len(remaining) == len(initial_findings) - 3
    assert not [finding for finding in remaining if finding.source_id == 10]
    assert [
        finding.source_id for finding in remaining if finding.code == "DUPLICATE_SOURCE_ID"
    ] == [
        4,
        4,
    ]
    assert {finding.source_id for finding in remaining if finding.code == "SAFETY_RISK"} == {
        5,
        11,
    }

    response = client.post(
        f"/admin/hardware/{source_six['id']}/edit",
        data={
            "name": source_six["name"],
            "brand": source_six["brand"],
            "purchase_date": "",
            "status": source_six["status"],
            "notes": source_six["notes"],
            "legacy_history": source_six["legacy_history"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    cleared = hardware.get(Query().source_id == 6)
    assert cleared is not None
    assert cleared["raw_payload"]["purchaseDate"] == "2027-10-10"
    assert cleared["purchase_date"] is None

    source_six_findings = [
        finding
        for finding in find_issues(hardware.all(), date(2026, 7, 22))
        if finding.source_id == 6
    ]
    assert [finding.code for finding in source_six_findings] == ["MISSING_PURCHASE_DATE"]
