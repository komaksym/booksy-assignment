import json
from datetime import date
from importlib.resources import files
from uuid import UUID

from fastapi import FastAPI

_EXPECTED_SOURCE_OBJECTS = [
    {
        "id": 1,
        "name": "Apple iPhone 13 Pro Max",
        "brand": "Apple",
        "purchaseDate": "2021-11-23",
        "status": "Available",
    },
    {
        "id": 2,
        "name": "Apple MacBook Pro 13",
        "brand": "Apple",
        "purchaseDate": "2021-12-20",
        "status": "In Use",
    },
    {
        "id": 3,
        "name": "Razer Basilisk V2",
        "brand": "Razer",
        "purchaseDate": "2021-06-05",
        "status": "Repair",
    },
    {
        "id": 4,
        "name": "SAMSUNG Galaxy S21",
        "brand": "Samsung",
        "purchaseDate": "2021-11-23",
        "status": "Available",
    },
    {
        "id": 5,
        "name": "Dell XPS 15 9510",
        "brand": "Dell",
        "purchaseDate": "2022-03-15",
        "status": "Available",
        "notes": "Battery swelling, do not issue without service.",
    },
    {
        "id": 6,
        "name": "Logitech MX Master 3",
        "brand": "Logitech",
        "purchaseDate": "2027-10-10",
        "status": "Available",
    },
    {
        "id": 7,
        "name": "Sony WH-1000XM4",
        "brand": "Sony",
        "purchaseDate": "2022-01-12",
        "status": "In Use",
        "assignedTo": "j.doe@booksy.com",
    },
    {
        "id": 4,
        "name": "Duplicate ID Test Laptop",
        "brand": "Lenovo",
        "purchaseDate": "2023-01-01",
        "status": "Repair",
    },
    {
        "id": 9,
        "name": "iPad Pro 12.9",
        "brand": "Appel",
        "purchaseDate": "22-05-2023",
        "status": "Available",
    },
    {
        "id": 10,
        "name": "Unknown Device",
        "brand": "",
        "purchaseDate": None,
        "status": "Unknown",
    },
    {
        "id": 11,
        "name": "MacBook Air M2",
        "brand": "Apple",
        "purchaseDate": "2023-08-01",
        "status": "Available",
        "history": "Returned by user with liquid damage. Keyboard sticky.",
    },
]


def test_seed_import_is_lossless_idempotent_and_reports_exact_findings(
    client, app: FastAPI
) -> None:
    """The dirty source is preserved while objective issues stay deterministic."""
    del client  # Starts and stops the application lifespan used for initialization.

    from hardware_hub.inventory import import_seed
    from hardware_hub.rules import find_issues

    fixture = json.loads(
        files("hardware_hub").joinpath("data/hardware_seed.json").read_text(encoding="utf-8")
    )
    hardware = app.state.hardware
    metadata = app.state.metadata
    records = hardware.all()

    assert fixture == _EXPECTED_SOURCE_OBJECTS
    assert len(records) == 11
    assert [record["raw_payload"] for record in records] == _EXPECTED_SOURCE_OBJECTS
    assert [record["source_id"] for record in records] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        4,
        9,
        10,
        11,
    ]

    duplicate_ids = [record["id"] for record in records if record["source_id"] == 4]
    assert len(duplicate_ids) == 2
    assert len(set(duplicate_ids)) == 2
    for hardware_id in duplicate_ids:
        assert str(UUID(hardware_id)) == hardware_id

    assert import_seed(hardware, metadata) == 0
    assert len(hardware) == 11

    hardware.truncate()
    assert import_seed(hardware, metadata) == 0
    assert hardware.all() == []

    findings = find_issues(records, date(2026, 7, 22))
    actual = {
        (finding.code, finding.severity, finding.source_id, finding.hardware_id)
        for finding in findings
    }
    by_source_id = {
        record["source_id"]: record["id"] for record in records if record["source_id"] != 4
    }
    expected = {
        ("DUPLICATE_SOURCE_ID", "warning", 4, duplicate_ids[0]),
        ("DUPLICATE_SOURCE_ID", "warning", 4, duplicate_ids[1]),
        ("FUTURE_PURCHASE_DATE", "warning", 6, by_source_id[6]),
        ("INVALID_PURCHASE_DATE", "warning", 9, by_source_id[9]),
        ("MISSING_BRAND", "warning", 10, by_source_id[10]),
        ("MISSING_PURCHASE_DATE", "warning", 10, by_source_id[10]),
        ("INVALID_STATUS", "critical", 10, by_source_id[10]),
        ("UNRESOLVED_HOLDER", "critical", 2, by_source_id[2]),
        ("UNRESOLVED_HOLDER", "critical", 7, by_source_id[7]),
        ("SAFETY_RISK", "critical", 5, by_source_id[5]),
        ("SAFETY_RISK", "critical", 11, by_source_id[11]),
    }

    assert actual == expected
    assert len(findings) == 11
    assert all(finding.source_id != 8 for finding in findings)
    assert [finding.code for finding in findings if finding.source_id == 9] == [
        "INVALID_PURCHASE_DATE"
    ]
