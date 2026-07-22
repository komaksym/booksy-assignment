from copy import deepcopy
from datetime import date

from fastapi import FastAPI
from tinydb import Query

from hardware_hub.auth import create_user
from hardware_hub.rules import find_issues


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
