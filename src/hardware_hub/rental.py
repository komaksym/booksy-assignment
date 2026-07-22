"""Guarded synchronous rent and return transitions."""

from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any

from tinydb import Query
from tinydb.table import Table

from hardware_hub.rules import find_issues


class RentalConflictError(RuntimeError):
    """Represent a rejected rental transition caused by current item state."""


class RentalPermissionError(RuntimeError):
    """Represent a rejected rental transition caused by ownership."""


def _load_record(
    hardware: Table, internal_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    records = hardware.all()
    record = next((item for item in records if item.get("id") == internal_id), None)
    return records, record


def _apply_transition(
    hardware: Table, record: dict[str, Any], action: str, user_id: str
) -> dict[str, Any]:
    occurred_at = datetime.now(UTC).isoformat()
    updated = deepcopy(record)
    updated["status"] = "In Use" if action == "rent" else "Available"
    updated["holder_user_id"] = user_id if action == "rent" else None
    updated["rental_history"] = [
        *list(record.get("rental_history", [])),
        {"type": action, "user_id": user_id, "occurred_at": occurred_at},
    ]
    updated["updated_at"] = occurred_at
    hardware.update(updated, Query().id == record["id"])
    return updated


def rent_hardware(hardware: Table, internal_id: str, user_id: str) -> dict[str, Any] | None:
    """Rent one currently safe and available hardware item to an ordinary user."""

    records, record = _load_record(hardware, internal_id)
    if record is None:
        return None
    if record.get("status") != "Available" or record.get("holder_user_id") is not None:
        raise RentalConflictError("This item is not available to rent.")
    if any(
        finding.hardware_id == internal_id and finding.severity == "critical"
        for finding in find_issues(records, date.today())
    ):
        raise RentalConflictError("This item is blocked by a critical safety check.")
    return _apply_transition(hardware, record, "rent", user_id)


def return_hardware(hardware: Table, internal_id: str, user_id: str) -> dict[str, Any] | None:
    """Return one item when the supplied user is its current application holder."""

    _, record = _load_record(hardware, internal_id)
    if record is None:
        return None
    if record.get("holder_user_id") is None:
        raise RentalConflictError("This item is not currently rented.")
    if record.get("holder_user_id") != user_id:
        raise RentalPermissionError("Only the current holder can return this item.")
    return _apply_transition(hardware, record, "return", user_id)
