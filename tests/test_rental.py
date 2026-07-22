import re
from copy import deepcopy
from datetime import date, datetime, timedelta

from fastapi import FastAPI
from tinydb import Query

from hardware_hub.auth import create_user
from hardware_hub.rules import find_issues


def _login(client, email: str, password: str = "user-password") -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _logout(client) -> None:
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303


def _source(hardware, source_id: int) -> dict[str, object]:
    record = hardware.get(Query().source_id == source_id)
    assert record is not None
    return record


def _edit_form(
    record: dict[str, object],
    *,
    status: str = "Keep current",
    notes: str | None = None,
) -> dict[str, str]:
    return {
        "name": str(record["name"]),
        "brand": str(record.get("brand") or ""),
        "purchase_date": str(record.get("purchase_date") or ""),
        "status": status,
        "notes": notes if notes is not None else str(record.get("notes") or ""),
        "legacy_history": str(record.get("legacy_history") or ""),
    }


def _assert_unrelated_fields_unchanged(before: dict[str, object], after: dict[str, object]) -> None:
    for key, value in before.items():
        if key not in {"status", "holder_user_id", "rental_history", "updated_at"}:
            assert after[key] == value


def _dashboard_row(page: str, internal_id: str) -> str:
    link = f'href="/hardware/{internal_id}"'
    start = page.index(link)
    return page[page.rfind("<tr", 0, start) : page.index("</tr>", start)]


def _history_markup(page: str) -> str:
    history = re.search(
        r'<section[^>]*data-testid="rental-history"[^>]*>(.*?)</section>',
        page,
        re.DOTALL,
    )
    assert history is not None
    return history.group(1)


def test_ordinary_inventory_exposes_safe_actions_without_private_data(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    ordinary = create_user(app.state.users, "viewer@booksy.test", "user-password")
    source_one = _source(hardware, 1)
    source_two = _source(hardware, 2)
    source_three = _source(hardware, 3)
    source_five = _source(hardware, 5)
    source_ten = _source(hardware, 10)
    hardware.update({"brand": "Confidential Canonical Brand"}, Query().id == source_ten["id"])
    _login(client, ordinary["email"])

    dashboard = client.get("/")

    assert dashboard.status_code == 200
    assert "Confidential Canonical Brand" not in dashboard.text
    assert all(
        set(row)
        == {
            "id",
            "name",
            "brand",
            "purchase_date",
            "status",
            "rental_action",
            "rental_reason",
        }
        for row in dashboard.context["records"]
    )
    assert f'href="/hardware/{source_one["id"]}"' in dashboard.text
    assert f'<form method="post" action="/hardware/{source_one["id"]}/rent">' in dashboard.text
    assert "Blocked by safety check" in _dashboard_row(dashboard.text, str(source_five["id"]))
    assert "Under repair" in _dashboard_row(dashboard.text, str(source_three["id"]))
    assert "Unavailable" in _dashboard_row(dashboard.text, str(source_two["id"]))

    empty = client.get("/?name=no-such-hardware")
    assert empty.status_code == 200
    assert '<td colspan="5" class="empty-state">' in empty.text

    available_detail = client.get(f"/hardware/{source_one['id']}")
    assert available_detail.status_code == 200
    assert (
        f'<form method="post" action="/hardware/{source_one["id"]}/rent">' in available_detail.text
    )

    blocked_detail = client.get(f"/hardware/{source_five['id']}")
    assert blocked_detail.status_code == 200
    assert f"/hardware/{source_five['id']}/rent" not in blocked_detail.text
    assert "Blocked by safety check" in blocked_detail.text
    assert "Battery swelling" not in blocked_detail.text

    assert client.get(f"/hardware/{source_ten['id']}").status_code == 404


def test_rent_enforces_safety_and_repetition_but_allows_warning_multiple_holdings(
    client, app: FastAPI
) -> None:
    hardware = app.state.hardware
    user = create_user(app.state.users, "renter@booksy.test", "user-password")
    source_one = _source(hardware, 1)
    source_four = _source(hardware, 4)
    source_five = _source(hardware, 5)
    _login(client, user["email"])

    blocked_before = deepcopy(source_five)
    blocked = client.post(f"/hardware/{source_five['id']}/rent", follow_redirects=False)
    assert blocked.status_code == 409
    assert hardware.get(Query().id == source_five["id"]) == blocked_before

    before_rent = deepcopy(source_one)
    rented_response = client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False)
    assert rented_response.status_code == 303
    assert rented_response.headers["location"] == f"/hardware/{source_one['id']}"
    rented = hardware.get(Query().id == source_one["id"])
    assert rented is not None
    assert rented["status"] == "In Use"
    assert rented["holder_user_id"] == user["id"]
    assert [event["type"] for event in rented["rental_history"]] == ["rent"]
    assert set(rented["rental_history"][0]) == {"type", "user_id", "occurred_at"}
    assert datetime.fromisoformat(rented["updated_at"]).utcoffset() == timedelta(0)
    assert rented["updated_at"] == rented["rental_history"][0]["occurred_at"]
    _assert_unrelated_fields_unchanged(before_rent, rented)

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert f'<form method="post" action="/hardware/{source_one["id"]}/return">' in _dashboard_row(
        dashboard.text, str(source_one["id"])
    )
    detail = client.get(f"/hardware/{source_one['id']}")
    assert detail.status_code == 200
    assert f'<form method="post" action="/hardware/{source_one["id"]}/return">' in detail.text

    repeated_before = deepcopy(rented)
    repeated = client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False)
    assert repeated.status_code == 409
    assert hardware.get(Query().id == source_one["id"]) == repeated_before

    warning_rent = client.post(f"/hardware/{source_four['id']}/rent", follow_redirects=False)
    assert warning_rent.status_code == 303
    warning_rented = hardware.get(Query().id == source_four["id"])
    assert warning_rented is not None
    assert warning_rented["holder_user_id"] == user["id"]
    assert hardware.get(Query().id == source_one["id"])["holder_user_id"] == user["id"]


def test_return_enforces_owner_and_role_while_history_stays_private(client, app: FastAPI) -> None:
    hardware = app.state.hardware
    first_user = create_user(app.state.users, "first@booksy.test", "user-password")
    second_user = create_user(app.state.users, "second@booksy.test", "user-password")
    source_one = _source(hardware, 1)
    source_seven = _source(hardware, 7)
    source_ten = _source(hardware, 10)

    _login(client, first_user["email"])
    assert (
        client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False).status_code == 303
    )
    rented = hardware.get(Query().id == source_one["id"])
    assert rented is not None

    _logout(client)
    _login(client, second_user["email"])
    second_detail = client.get(f"/hardware/{source_one['id']}")
    assert second_detail.status_code == 200
    second_history = _history_markup(second_detail.text)
    assert "Another user" in second_history
    assert first_user["email"] not in second_history
    assert second_user["email"] not in second_history
    wrong_owner_before = deepcopy(rented)
    wrong_owner = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert wrong_owner.status_code == 403
    assert hardware.get(Query().id == source_one["id"]) == wrong_owner_before

    _logout(client)
    _login(client, "admin@booksy.test", "admin-password")
    admin_detail = client.get(f"/hardware/{source_one['id']}")
    assert admin_detail.status_code == 200
    assert first_user["email"] in admin_detail.text
    assert "Original import" in admin_detail.text
    assert f"/hardware/{source_one['id']}/rent" not in admin_detail.text
    assert f"/hardware/{source_one['id']}/return" not in admin_detail.text
    legacy_detail = client.get(f"/hardware/{source_seven['id']}")
    assert legacy_detail.status_code == 200
    assert "j.doe@booksy.com" not in legacy_detail.text
    assert client.get(f"/hardware/{source_ten['id']}").status_code == 200
    for action in ("rent", "return"):
        admin_before = deepcopy(hardware.get(Query().id == source_one["id"]))
        response = client.post(f"/hardware/{source_one['id']}/{action}", follow_redirects=False)
        assert response.status_code == 403
        assert hardware.get(Query().id == source_one["id"]) == admin_before

    _logout(client)
    _login(client, first_user["email"])
    before_return = deepcopy(hardware.get(Query().id == source_one["id"]))
    returned_response = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert returned_response.status_code == 303
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
    _assert_unrelated_fields_unchanged(before_return, returned)

    owner_detail = client.get(f"/hardware/{source_one['id']}")
    owner_history = _history_markup(owner_detail.text)
    assert owner_history.index("<strong>Return</strong>") < owner_history.index(
        "<strong>Rent</strong>"
    )
    assert owner_history.count("You") == 2
    assert first_user["id"] not in owner_history

    _logout(client)
    _login(client, "admin@booksy.test", "admin-password")
    app.state.users.remove(Query().id == first_user["id"])
    unknown_actor = client.get(f"/hardware/{source_one['id']}")
    assert unknown_actor.status_code == 200
    assert "Unknown user" in unknown_actor.text
    assert first_user["id"] not in unknown_actor.text

    _logout(client)
    _login(client, second_user["email"])
    assert client.get(f"/hardware/{source_ten['id']}").status_code == 404
    repeated_before = deepcopy(returned)
    repeated = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert repeated.status_code == 409
    assert hardware.get(Query().id == source_one["id"]) == repeated_before


def test_owner_can_return_after_admin_adds_safety_evidence_and_next_rent_is_blocked(
    client, app: FastAPI
) -> None:
    hardware = app.state.hardware
    holder = create_user(app.state.users, "safety-holder@booksy.test", "user-password")
    source_one = _source(hardware, 1)

    _login(client, holder["email"])
    assert (
        client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False).status_code == 303
    )
    held = hardware.get(Query().id == source_one["id"])
    assert held is not None

    _logout(client)
    _login(client, "admin@booksy.test", "admin-password")
    edit = client.post(
        f"/admin/hardware/{source_one['id']}/edit",
        data=_edit_form(held, notes="Battery swelling reported during the rental."),
        follow_redirects=False,
    )
    assert edit.status_code == 303
    safety_noted = hardware.get(Query().id == source_one["id"])
    assert safety_noted is not None
    assert safety_noted["status"] == "In Use"
    assert safety_noted["holder_user_id"] == holder["id"]
    assert safety_noted["rental_history"] == held["rental_history"]
    assert "battery swelling" in safety_noted["notes"].lower()

    _logout(client)
    _login(client, holder["email"])
    returned_response = client.post(f"/hardware/{source_one['id']}/return", follow_redirects=False)
    assert returned_response.status_code == 303
    returned = hardware.get(Query().id == source_one["id"])
    assert returned is not None
    assert returned["status"] == "Available"
    assert returned["holder_user_id"] is None
    assert any(
        finding.hardware_id == source_one["id"] and finding.code == "SAFETY_RISK"
        for finding in find_issues(hardware.all(), date.today())
    )

    before_blocked_rent = deepcopy(returned)
    blocked = client.post(f"/hardware/{source_one['id']}/rent", follow_redirects=False)
    assert blocked.status_code == 409
    assert "blocked by a critical safety check" in blocked.text
    assert hardware.get(Query().id == source_one["id"]) == before_blocked_rent
