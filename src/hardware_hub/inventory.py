"""Seed import and canonical conversion for the hardware inventory."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from importlib.resources import files
from uuid import uuid4

from tinydb import Query
from tinydb.table import Table

_SEED_MARKER = "hardware_seed_loaded"
_SUPPORTED_STATUSES = {"Available", "In Use", "Repair"}


def import_seed(hardware: Table, metadata: Table) -> int:
    """Import the bundled fixture once, preserving every source object exactly."""

    marker = Query()
    if metadata.contains(marker.key == _SEED_MARKER):
        return 0
    if len(hardware) > 0:
        metadata.insert({"key": _SEED_MARKER})
        return 0

    source = _load_fixture()
    documents = [_convert_source(record) for record in source]
    hardware.insert_multiple(documents)
    metadata.insert({"key": _SEED_MARKER})
    return len(documents)


def _load_fixture() -> list[dict[object, object]]:
    fixture = json.loads(
        files("hardware_hub").joinpath("data/hardware_seed.json").read_text(encoding="utf-8")
    )
    if not isinstance(fixture, list) or len(fixture) != 11:
        raise ValueError("Hardware seed must be a list of exactly 11 objects")
    if not all(isinstance(record, dict) for record in fixture):
        raise ValueError("Hardware seed entries must be objects")
    return fixture


def _convert_source(source: dict[object, object]) -> dict[str, object]:
    name = source.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Hardware seed names must be non-blank strings")

    raw_brand = source.get("brand")
    brand = raw_brand.strip() if isinstance(raw_brand, str) and raw_brand.strip() else None
    raw_date = source.get("purchaseDate")
    purchase_date = raw_date if _is_strict_date(raw_date) else None
    raw_status = source.get("status")
    status = raw_status if raw_status in _SUPPORTED_STATUSES else None
    now = datetime.now(UTC).isoformat()

    return {
        "id": str(uuid4()),
        "source_id": source.get("id"),
        "raw_payload": deepcopy(source),
        "name": name.strip(),
        "brand": brand,
        "purchase_date": purchase_date,
        "status": status,
        "notes": source.get("notes", "") if isinstance(source.get("notes", ""), str) else "",
        "legacy_history": (
            source.get("history", "") if isinstance(source.get("history", ""), str) else ""
        ),
        "holder_user_id": None,
        "rental_history": [],
        "created_at": now,
        "updated_at": now,
    }


def _is_strict_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
