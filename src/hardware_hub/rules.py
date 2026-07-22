"""Pure deterministic hardware inventory findings."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

# Canonical status values that the application treats as valid operational state.
_SUPPORTED_STATUSES = {"Available", "In Use", "Repair"}
# Exact case-insensitive phrases that make an Available item a safety risk.
_SAFETY_PHRASES = ("battery swelling", "liquid damage")


@dataclass(frozen=True)
class Finding:
    """An immutable, derived problem with one hardware record."""

    code: str
    severity: Literal["warning", "critical"]
    hardware_id: str
    source_id: object | None


def find_issues(records: list[dict[str, object]], today: date) -> tuple[Finding, ...]:
    """Return deterministic findings without reading or mutating external state."""

    source_counts: dict[object, int] = {}
    for record in records:
        source_id = record.get("source_id")
        if source_id is not None:
            source_counts[source_id] = source_counts.get(source_id, 0) + 1

    findings: list[Finding] = []
    for record in records:
        hardware_id = record["id"]
        if not isinstance(hardware_id, str):
            raise ValueError("Hardware record IDs must be strings")
        source_id = record.get("source_id")
        raw = record.get("raw_payload")
        raw_payload = raw if isinstance(raw, dict) else {}
        raw_date = raw_payload.get("purchaseDate")
        purchase_date = record.get("purchase_date")
        raw_status = raw_payload.get("status")
        status = record.get("status")

        if source_id is not None and source_counts[source_id] > 1:
            findings.append(_finding("DUPLICATE_SOURCE_ID", "warning", hardware_id, source_id))
        if _is_after_today(purchase_date, today):
            findings.append(_finding("FUTURE_PURCHASE_DATE", "warning", hardware_id, source_id))
        if raw_date is not None and not _is_strict_date(raw_date) and purchase_date is None:
            findings.append(_finding("INVALID_PURCHASE_DATE", "warning", hardware_id, source_id))
        if raw_date is None and purchase_date is None:
            findings.append(_finding("MISSING_PURCHASE_DATE", "warning", hardware_id, source_id))
        if not isinstance(record.get("brand"), str) or not record["brand"].strip():
            findings.append(_finding("MISSING_BRAND", "warning", hardware_id, source_id))
        if raw_status not in _SUPPORTED_STATUSES and status is None:
            findings.append(_finding("INVALID_STATUS", "critical", hardware_id, source_id))
        if status == "In Use" and record.get("holder_user_id") is None:
            findings.append(_finding("UNRESOLVED_HOLDER", "critical", hardware_id, source_id))
        if status == "Available" and _has_safety_evidence(record, raw_payload):
            findings.append(_finding("SAFETY_RISK", "critical", hardware_id, source_id))

    return tuple(findings)


def _finding(
    code: str,
    severity: Literal["warning", "critical"],
    hardware_id: str,
    source_id: object | None,
) -> Finding:
    """Construct one immutable finding value for a hardware item."""

    return Finding(code, severity, hardware_id, source_id)


def _is_strict_date(value: object) -> bool:
    """Return whether a value is a real date in exact ``YYYY-MM-DD`` form."""

    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_after_today(value: object, today: date) -> bool:
    """Return whether a valid canonical purchase date lies after ``today``."""

    return _is_strict_date(value) and date.fromisoformat(value) > today


def _has_safety_evidence(record: dict[str, object], raw_payload: dict[object, object]) -> bool:
    """Detect exact safety phrases in immutable or editable notes/history."""

    evidence = (
        raw_payload.get("notes", ""),
        raw_payload.get("history", ""),
        record.get("notes", ""),
        record.get("legacy_history", ""),
    )
    return any(
        phrase in value.lower()
        for value in evidence
        if isinstance(value, str)
        for phrase in _SAFETY_PHRASES
    )
