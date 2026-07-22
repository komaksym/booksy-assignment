from copy import deepcopy
from datetime import datetime, timedelta

from fastapi import FastAPI
from tinydb import Query

from hardware_hub.auth import create_user


def _login(client, email: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": "user-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _assert_unrelated_fields_unchanged(before: dict[str, object], after: dict[str, object]) -> None:
    for key, value in before.items():
        if key not in {"status", "holder_user_id", "rental_history", "updated_at"}:
            assert after[key] == value


def test_rent_and_return_enforce_safety_ownership_and_history(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    first_user = create_user(app.state.users, "first@booksy.test", "user-password")
    second_user = create_user(app.state.users, "second@booksy.test", "user-password")
    source_one = hardware.get(Query().source_id == 1)
    source_four = hardware.get(Query().source_id == 4)
    source_five = hardware.get(Query().source_id == 5)
    assert source_one is not None
    assert source_four is not None
    assert source_five is not None

    _login(client, first_user["email"])

    blocked_before = deepcopy(source_five)
    response = client.post(f"/hardware/{source_five['id']}/rent", follow_redirects=False)
    assert response.status_code == 409
    assert hardware.get(Query().id == source_five["id"]) == blocked_before

    source_one_before_rent = deepcopy(source_one)
    response = client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/hardware/{source_one['id']}"
    rented = hardware.get(Query().id == source_one["id"])
    assert rented is not None
    assert rented["status"] == "In Use"
    assert rented["holder_user_id"] == first_user["id"]
    assert [event["type"] for event in rented["rental_history"]] == ["rent"]
    assert set(rented["rental_history"][0]) == {"type", "user_id", "occurred_at"}
    assert datetime.fromisoformat(rented["updated_at"]).utcoffset() == timedelta(0)
    assert rented["updated_at"] == rented["rental_history"][0]["occurred_at"]
    _assert_unrelated_fields_unchanged(source_one_before_rent, rented)

    repeated_rent_before = deepcopy(rented)
    response = client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False)
    assert response.status_code == 409
    assert hardware.get(Query().id == source_one["id"]) == repeated_rent_before

    response = client.post(f"/hardware/{source_four['id']}/rent", follow_redirects=False)
    assert response.status_code == 303
    warning_rented = hardware.get(Query().id == source_four["id"])
    assert warning_rented is not None
    assert warning_rented["holder_user_id"] == first_user["id"]

    client.post("/logout", follow_redirects=False)
    _login(client, second_user["email"])
    wrong_owner_before = deepcopy(rented)
    response = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert response.status_code == 403
    assert hardware.get(Query().id == source_one["id"]) == wrong_owner_before

    client.post("/logout", follow_redirects=False)
    response = client.post(
        "/login",
        data={"email": "admin@booksy.test", "password": "admin-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    for action in ("rent", "return"):
        admin_before = deepcopy(hardware.get(Query().id == source_one["id"]))
        response = client.post(f"/hardware/{source_one['id']}/{action}", follow_redirects=False)
        assert response.status_code == 403
        assert hardware.get(Query().id == source_one["id"]) == admin_before

    client.post("/logout", follow_redirects=False)
    _login(client, first_user["email"])
    source_one_before_return = deepcopy(hardware.get(Query().id == source_one["id"]))
    response = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert response.status_code == 303
    returned = hardware.get(Query().id == source_one["id"])
    assert returned is not None
    assert returned["status"] == "Available"
    assert returned["holder_user_id"] is None
    assert [event["type"] for event in returned["rental_history"]] == ["rent", "return"]
    assert [event["user_id"] for event in returned["rental_history"]] == [
        first_user["id"],
        first_user["id"],
    ]
    for event in returned["rental_history"]:
        assert datetime.fromisoformat(event["occurred_at"]).utcoffset() == timedelta(0)
    assert returned["updated_at"] == returned["rental_history"][-1]["occurred_at"]
    _assert_unrelated_fields_unchanged(source_one_before_return, returned)

    repeated_return_before = deepcopy(returned)
    response = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert response.status_code == 409
    assert hardware.get(Query().id == source_one["id"]) == repeated_return_before
