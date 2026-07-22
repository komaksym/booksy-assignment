"""Seed import and canonical conversion for the hardware inventory."""

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Any
from uuid import uuid4

from tinydb import Query
from tinydb.table import Table

_SEED_MARKER = "hardware_seed_loaded"
_SUPPORTED_STATUSES = {"Available", "In Use", "Repair"}
_MANUAL_STATUSES = {"Available", "Repair"}
_SORT_KEYS = {"name", "brand", "purchase_date", "status"}
_DIRECTIONS = {"asc", "desc"}
_STATUS_FILTERS = _SUPPORTED_STATUSES | {"Needs correction"}


class InventoryInputError(ValueError):
    """Represent a safe inventory validation message."""


class InventoryConflictError(RuntimeError):
    """Represent a safe rejected inventory transition."""


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


def filter_and_sort(
    records: list[dict[str, Any]],
    *,
    name: str = "",
    brand: str = "",
    purchase_date: str = "",
    status: str = "",
    sort: str = "name",
    direction: str = "asc",
) -> list[dict[str, Any]]:
    """Apply the dashboard's allowlisted AND filters and deterministic sort."""

    if purchase_date and not _is_strict_date(purchase_date):
        raise InventoryInputError("Purchase date must be a real date in YYYY-MM-DD format")
    if status and status not in _STATUS_FILTERS:
        raise InventoryInputError("Choose a supported status filter")
    if sort not in _SORT_KEYS:
        raise InventoryInputError("Choose a supported sort field")
    if direction not in _DIRECTIONS:
        raise InventoryInputError("Choose a supported sort direction")

    needle = name.casefold()
    filtered = [
        record
        for record in records
        if (not needle or needle in str(record.get("name", "")).casefold())
        and (not brand or record.get("brand") == brand)
        and (not purchase_date or record.get("purchase_date") == purchase_date)
        and (
            not status
            or (status == "Needs correction" and record.get("status") is None)
            or (status != "Needs correction" and record.get("status") == status)
        )
    ]

    present = [record for record in filtered if record.get(sort) is not None]
    missing = [record for record in filtered if record.get(sort) is None]
    present.sort(key=lambda record: str(record["id"]))
    present.sort(
        key=lambda record: str(record[sort]).casefold(),
        reverse=direction == "desc",
    )
    missing.sort(key=lambda record: str(record["id"]))
    return present + missing


def parse_hardware_candidate(
    form: Mapping[str, object],
    *,
    current_status: object = None,
    creating: bool,
) -> dict[str, object]:
    """Parse every editable field before a caller performs one write."""

    name = str(form.get("name", "")).strip()
    if not name:
        raise InventoryInputError("Name is required")

    raw_brand = str(form.get("brand", "")).strip()
    raw_date = str(form.get("purchase_date", "")).strip()
    if raw_date and not _is_strict_date(raw_date):
        raise InventoryInputError("Purchase date must be a real date in YYYY-MM-DD format")

    selected_status = str(form.get("status", ""))
    if creating:
        if selected_status not in _MANUAL_STATUSES:
            raise InventoryInputError("Choose Available or Repair")
        candidate_status: object = selected_status
    else:
        if selected_status == "Keep current":
            candidate_status = current_status
        elif selected_status in _MANUAL_STATUSES:
            candidate_status = selected_status
        else:
            raise InventoryInputError("Choose Keep current, Available, or Repair")

    return {
        "name": name,
        "brand": raw_brand or None,
        "purchase_date": raw_date or None,
        "status": candidate_status,
        "notes": str(form.get("notes", "")),
        "legacy_history": str(form.get("legacy_history", "")),
    }


def create_hardware(hardware: Table, form: Mapping[str, object]) -> dict[str, object]:
    """Create one manual hardware document from an accepted full candidate."""

    candidate = parse_hardware_candidate(form, creating=True)
    now = datetime.now(UTC).isoformat()
    record = {
        "id": str(uuid4()),
        "source_id": None,
        "raw_payload": None,
        **candidate,
        "holder_user_id": None,
        "rental_history": [],
        "created_at": now,
        "updated_at": now,
    }
    hardware.insert(record)
    return record


def update_hardware(
    hardware: Table,
    internal_id: str,
    form: Mapping[str, object],
) -> dict[str, object] | None:
    """Re-read and update one internal-ID document after full validation."""

    query = Query()
    current = hardware.get(query.id == internal_id)
    if current is None:
        return None
    candidate = parse_hardware_candidate(
        form,
        current_status=current.get("status"),
        creating=False,
    )
    if current.get("holder_user_id") is not None and candidate["status"] != current.get("status"):
        raise InventoryConflictError("Status cannot change while hardware has a holder")
    candidate["updated_at"] = datetime.now(UTC).isoformat()
    hardware.update(candidate, query.id == internal_id)
    return hardware.get(query.id == internal_id)


def delete_hardware(hardware: Table, internal_id: str) -> bool:
    """Remove exactly one holderless internal-ID document."""

    query = Query()
    current = hardware.get(query.id == internal_id)
    if current is None:
        return False
    if current.get("holder_user_id") is not None:
        raise InventoryConflictError("Hardware with a holder cannot be deleted")
    hardware.remove(query.id == internal_id)
    return True


def transition_repair(
    hardware: Table,
    internal_id: str,
    *,
    expected: str,
    target: str,
) -> dict[str, object] | None:
    """Apply one exact holderless repair transition after re-reading state."""

    query = Query()
    current = hardware.get(query.id == internal_id)
    if current is None:
        return None
    if current.get("holder_user_id") is not None:
        raise InventoryConflictError("Repair status cannot change while hardware has a holder")
    if current.get("status") != expected:
        raise InventoryConflictError(f"Hardware must be {expected} for this action")
    hardware.update(
        {"status": target, "updated_at": datetime.now(UTC).isoformat()},
        query.id == internal_id,
    )
    return hardware.get(query.id == internal_id)
