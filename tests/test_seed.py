import json
from datetime import date
from importlib.resources import files
from uuid import UUID

from fastapi import FastAPI


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

    assert len(records) == 11
    assert [record["raw_payload"] for record in records] == fixture
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
    actual = {(finding.code, finding.source_id, finding.hardware_id) for finding in findings}
    by_source_id = {
        record["source_id"]: record["id"] for record in records if record["source_id"] != 4
    }
    expected = {
        ("DUPLICATE_SOURCE_ID", 4, duplicate_ids[0]),
        ("DUPLICATE_SOURCE_ID", 4, duplicate_ids[1]),
        ("FUTURE_PURCHASE_DATE", 6, by_source_id[6]),
        ("INVALID_PURCHASE_DATE", 9, by_source_id[9]),
        ("MISSING_BRAND", 10, by_source_id[10]),
        ("MISSING_PURCHASE_DATE", 10, by_source_id[10]),
        ("INVALID_STATUS", 10, by_source_id[10]),
        ("UNRESOLVED_HOLDER", 2, by_source_id[2]),
        ("UNRESOLVED_HOLDER", 7, by_source_id[7]),
        ("SAFETY_RISK", 5, by_source_id[5]),
        ("SAFETY_RISK", 11, by_source_id[11]),
    }

    assert actual == expected
    assert len(findings) == 11
    assert all(finding.source_id != 8 for finding in findings)
    assert [finding.code for finding in findings if finding.source_id == 9] == [
        "INVALID_PURCHASE_DATE"
    ]
