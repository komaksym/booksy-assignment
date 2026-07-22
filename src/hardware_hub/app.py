"""FastAPI composition and HTTP routes for Hardware Hub."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from hardware_hub.audit import (
    AuditUnavailableError,
    LLMFinding,
    build_ai_rows,
    build_audit_snapshot,
    build_deterministic_rows,
    llm_configuration_status,
    request_deepseek_audit,
)
from hardware_hub.auth import (
    UserInputError,
    authenticate,
    bootstrap_admin,
    create_user,
    current_user,
)
from hardware_hub.config import Settings
from hardware_hub.db import hardware_table, metadata_table, open_db, users_table
from hardware_hub.inventory import (
    InventoryConflictError,
    InventoryInputError,
    create_hardware,
    delete_hardware,
    filter_and_sort,
    import_seed,
    transition_repair,
    update_hardware,
)
from hardware_hub.rental import (
    RentalConflictError,
    RentalPermissionError,
    rent_hardware,
    return_hardware,
)
from hardware_hub.rules import Finding, find_issues

_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
_ORIGINAL_SOURCE_COUNT = 11
_ORDINARY_STATUS_CHOICES = ("Available", "In Use", "Repair")
_ADMIN_STATUS_CHOICES = (*_ORDINARY_STATUS_CHOICES, "Needs correction")


def _status_choices(user: dict[str, Any]) -> tuple[str, ...]:
    """Return the dashboard status filters available to the current role."""

    return _ADMIN_STATUS_CHOICES if user["role"] == "admin" else _ORDINARY_STATUS_CHOICES


def _dashboard_record(record: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Project one stored record to the fields rendered by its dashboard role."""

    fields = ["id", "name", "brand", "purchase_date", "status"]
    if user["role"] == "admin":
        fields.insert(1, "source_id")
    return {field: record.get(field) for field in fields}


def _dashboard_context(
    *,
    user: dict[str, Any],
    all_records: list[dict[str, Any]],
    visible_records: list[dict[str, Any]],
    records: list[dict[str, Any]],
    filters: dict[str, str],
    error: str | None,
) -> dict[str, Any]:
    """Build template-ready dashboard state without mutating stored hardware.

    ``all_records`` drives circulation decisions, ``visible_records`` supplies
    role-safe filter choices, and ``records`` is the filtered/sorted table subset.
    Each table row is copied before presentation-only state is attached.
    """

    findings = find_issues(all_records, date.today())
    by_hardware: dict[str, list[Finding]] = {}
    for finding in findings:
        by_hardware.setdefault(finding.hardware_id, []).append(finding)

    rows = []
    for record in records:
        row = _dashboard_record(record, user)
        record_findings = by_hardware.get(str(record["id"]), [])
        if user["role"] == "admin":
            row["findings"] = record_findings
            row["repair_action"] = (
                "mark-repair"
                if record.get("holder_user_id") is None and record.get("status") == "Available"
                else "clear-repair"
                if record.get("holder_user_id") is None and record.get("status") == "Repair"
                else None
            )
        else:
            row.update(_circulation_action(record, user, record_findings))
        rows.append(row)

    brands = sorted(
        {
            str(record["brand"])
            for record in visible_records
            if isinstance(record.get("brand"), str) and record["brand"]
        },
        key=str.casefold,
    )
    return {
        "user": user,
        "records": rows,
        "filters": filters,
        "brands": brands,
        "status_choices": _status_choices(user),
        "error": error,
        "source_count": sum(record.get("source_id") is not None for record in all_records),
        "original_source_count": _ORIGINAL_SOURCE_COUNT,
        "finding_count": len(findings),
        "rule_count": len({finding.code for finding in findings}),
    }


def _form_values(record: dict[str, Any] | None = None) -> dict[str, object]:
    """Return editable values for one hardware item or a blank creation form.

    A ``record`` here is the complete stored document for one hardware item, not
    an individual field within that item.
    """

    if record is None:
        return {
            "name": "",
            "brand": "",
            "purchase_date": "",
            "status": "Available",
            "notes": "",
            "legacy_history": "",
        }
    return {
        "name": record.get("name", ""),
        "brand": record.get("brand") or "",
        "purchase_date": record.get("purchase_date") or "",
        "status": "Keep current",
        "notes": record.get("notes", ""),
        "legacy_history": record.get("legacy_history", ""),
    }


def _submitted_values(form: Any) -> dict[str, object]:
    """Retain non-secret editable form values when validation rejects a request."""

    return {
        key: str(form.get(key, ""))
        for key in ("name", "brand", "purchase_date", "status", "notes", "legacy_history")
    }


def _original_import(record: dict[str, Any]) -> list[dict[str, str]]:
    """Return allowlisted source evidence for one item, redacting an assignee email."""

    raw = record.get("raw_payload")
    if not isinstance(raw, dict):
        return []
    fields = [
        ("Source ID", raw.get("id")),
        ("Name", raw.get("name")),
        ("Brand", raw.get("brand")),
        ("Purchase date", raw.get("purchaseDate")),
        ("Status", raw.get("status")),
    ]
    if "notes" in raw:
        fields.append(("Notes", raw.get("notes")))
    if "history" in raw:
        fields.append(("History", raw.get("history")))
    rendered = [
        {
            "label": label,
            "value": "null" if value is None else "blank" if value == "" else str(value),
        }
        for label, value in fields
    ]
    if "assignedTo" in raw:
        rendered.append({"label": "Legacy assignee", "value": "Legacy assignee present — redacted"})
    return rendered


def _hardware_form_context(
    *,
    user: dict[str, Any],
    record: dict[str, Any] | None,
    values: dict[str, object],
    error: str | None,
) -> dict[str, Any]:
    """Build create/edit template state and derive the currently valid repair action.

    The helper exposes only allowlisted raw evidence, and it offers a repair action
    only for a holderless item in exactly ``Available`` or ``Repair`` state. The
    mutation route repeats those checks server-side before writing.
    """

    repair_action = None
    delete_action = None
    delete_reason = None
    if record is not None and record.get("holder_user_id") is None:
        delete_action = "delete"
        if record.get("status") == "Available":
            repair_action = "mark-repair"
        elif record.get("status") == "Repair":
            repair_action = "clear-repair"
    elif record is not None:
        delete_reason = "This item cannot be deleted while it has a holder."
    return {
        "user": user,
        "record": record,
        "values": values,
        "error": error,
        "original_import": _original_import(record) if record is not None else [],
        "repair_action": repair_action,
        "delete_action": delete_action,
        "delete_reason": delete_reason,
    }


def _visible_hardware(hardware: Any, user: dict[str, Any], internal_id: str) -> dict[str, Any]:
    """Load one item by internal ID, concealing invalid canonical state from users."""

    record = hardware.get(lambda item: item.get("id") == internal_id)
    if record is None or (user["role"] != "admin" and record.get("status") is None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return record


def _circulation_action(
    record: dict[str, Any], user: dict[str, Any], record_findings: list[Finding]
) -> dict[str, str | None]:
    """Return the safe, presentation-only circulation action or reason for one item."""

    if user["role"] == "admin":
        return {"rental_action": None, "rental_reason": None}
    if record.get("status") == "Available" and record.get("holder_user_id") is None:
        if any(finding.severity == "critical" for finding in record_findings):
            return {"rental_action": None, "rental_reason": "Blocked by safety check"}
        return {"rental_action": "rent", "rental_reason": None}
    if record.get("status") == "In Use" and record.get("holder_user_id") == user["id"]:
        return {"rental_action": "return", "rental_reason": None}
    if record.get("status") == "In Use" and record.get("holder_user_id") is not None:
        return {"rental_action": None, "rental_reason": "Currently rented"}
    if record.get("status") == "Repair":
        return {"rental_action": None, "rental_reason": "Under repair"}
    return {"rental_action": None, "rental_reason": "Unavailable"}


def _rental_history_context(
    record: dict[str, Any], user: dict[str, Any], users_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    """Build newest-first, privacy-resolved rental activity for one detail page."""

    history = record.get("rental_history", [])
    if not isinstance(history, list):
        return []
    entries = []
    for event in reversed(history):
        if not isinstance(event, dict):
            continue
        actor = (
            users_by_id.get(str(event.get("user_id")), {}).get("email", "Unknown user")
            if user["role"] == "admin"
            else "You"
            if event.get("user_id") == user["id"]
            else "Another user"
        )
        event_type = event.get("type")
        label = (
            f"Administrator release to {event.get('target_status', 'Unknown')}"
            if event_type == "admin_release"
            else "Rent"
            if event_type == "rent"
            else "Return"
        )
        entries.append(
            {
                "label": label,
                "actor": str(actor),
                "occurred_at": str(event.get("occurred_at", "")),
            }
        )
    return entries


def _hardware_detail_context(
    *,
    user: dict[str, Any],
    record: dict[str, Any],
    all_records: list[dict[str, Any]],
    users: list[dict[str, Any]],
    error: str | None,
) -> dict[str, Any]:
    """Build privacy-aware display state for the canonical hardware detail page."""

    findings = find_issues(all_records, date.today())
    record_findings = [finding for finding in findings if finding.hardware_id == record["id"]]
    display_record = {
        key: record.get(key) for key in ("id", "name", "brand", "purchase_date", "status")
    }
    users_by_id = {
        str(candidate["id"]): candidate
        for candidate in users
        if isinstance(candidate.get("id"), str)
    }
    circulation = _circulation_action(record, user, record_findings)
    return {
        "user": user,
        "record": display_record,
        "rental_action": circulation["rental_action"],
        "rental_reason": circulation["rental_reason"],
        "rental_history": _rental_history_context(record, user, users_by_id),
        "findings": record_findings if user["role"] == "admin" else [],
        "original_import": _original_import(record) if user["role"] == "admin" else [],
        "error": error,
    }


def _detail_response(
    request: Request,
    user: dict[str, Any],
    internal_id: str,
    *,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    """Render a fresh canonical hardware detail response."""

    record = _visible_hardware(request.app.state.hardware, user, internal_id)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="hardware_detail.html",
        context=_hardware_detail_context(
            user=user,
            record=record,
            all_records=request.app.state.hardware.all(),
            users=request.app.state.users.all(),
            error=error,
        ),
        status_code=status_code,
    )


def _audit_context(
    *,
    user: dict[str, Any],
    records: list[dict[str, Any]],
    findings: tuple[Finding, ...],
    runtime: Settings,
    ai_findings: tuple[LLMFinding, ...] | None,
    warning: str | None,
) -> dict[str, Any]:
    """Build a fully validated, read-only audit-page presentation model."""

    configured, missing = llm_configuration_status(
        runtime.llm_base_url,
        runtime.llm_api_key,
        runtime.llm_model,
    )
    return {
        "user": user,
        "deterministic_rows": build_deterministic_rows(records, findings),
        "llm_configured": configured,
        "missing_llm_settings": missing,
        "warning": warning,
        "ai_rows": None if ai_findings is None else build_ai_rows(records, ai_findings),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured Hardware Hub application."""

    runtime = settings or Settings()
    if len(runtime.session_secret) < 16:
        raise RuntimeError("SESSION_SECRET must contain at least 16 characters")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = open_db(runtime.tinydb_path)
        app.state.db = db
        app.state.users = users_table(db)
        app.state.hardware = hardware_table(db)
        app.state.metadata = metadata_table(db)
        try:
            bootstrap_admin(
                app.state.users,
                runtime.bootstrap_admin_email,
                runtime.bootstrap_admin_password,
            )
            import_seed(app.state.hardware, app.state.metadata)
            yield
        finally:
            db.close()

    app = FastAPI(title="Hardware Hub", lifespan=lifespan)
    app.state.settings = runtime
    app.add_middleware(
        SessionMiddleware,
        secret_key=runtime.session_secret,
        # The locked Starlette version does not reissue unchanged sessions, so
        # read-only activity does not refresh this absolute maximum lifetime.
        max_age=_SESSION_MAX_AGE_SECONDS,
        same_site="strict",
        https_only=runtime.environment == "production",
    )
    app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")

    @app.get("/health", response_class=JSONResponse)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if current_user(request):
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": None, "email": ""},
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        form = await request.form()
        email = str(form.get("email", ""))
        password = str(form.get("password", ""))
        user = authenticate(request.app.state.users, email, password)
        if user is None:
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="login.html",
                context={"error": "Invalid email or password", "email": email.strip()},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        request.session.clear()
        request.session["user_id"] = user["id"]
        destination = "/admin/users" if user["role"] == "admin" else "/"
        return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        name: str = "",
        brand: str = "",
        purchase_date: str = "",
        status_filter: str = Query(default="", alias="status"),
        sort: str = "name",
        direction: str = "asc",
    ):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        all_records = request.app.state.hardware.all()
        visible = (
            all_records
            if user["role"] == "admin"
            else [record for record in all_records if record.get("status") is not None]
        )
        filters = {
            "name": name,
            "brand": brand,
            "purchase_date": purchase_date,
            "status": status_filter,
            "sort": sort,
            "direction": direction,
        }
        error = None
        response_status = status.HTTP_200_OK
        try:
            if status_filter and status_filter not in _status_choices(user):
                raise InventoryInputError("Choose a supported status filter")
            records = filter_and_sort(visible, **filters)
        except InventoryInputError as exc:
            error = str(exc)
            response_status = status.HTTP_400_BAD_REQUEST
            records = filter_and_sort(visible)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=_dashboard_context(
                user=user,
                all_records=all_records,
                visible_records=visible,
                records=records,
                filters=filters,
                error=error,
            ),
            status_code=response_status,
        )

    @app.post("/logout")
    async def logout(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        request.session.clear()
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/hardware/{internal_id}", response_class=HTMLResponse)
    async def hardware_detail(request: Request, internal_id: str):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return _detail_response(request, user, internal_id)

    async def rental_transition(request: Request, internal_id: str, *, action: str):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        _visible_hardware(request.app.state.hardware, user, internal_id)
        if user["role"] != "user":
            return _detail_response(
                request,
                user,
                internal_id,
                error="Administrators cannot rent or return hardware.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        try:
            updated = (
                rent_hardware(request.app.state.hardware, internal_id, user["id"])
                if action == "rent"
                else return_hardware(request.app.state.hardware, internal_id, user["id"])
            )
        except RentalConflictError as exc:
            return _detail_response(
                request,
                user,
                internal_id,
                error=str(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
        except RentalPermissionError as exc:
            return _detail_response(
                request,
                user,
                internal_id,
                error=str(exc),
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse(f"/hardware/{internal_id}", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/hardware/{internal_id}/rent")
    async def rent(request: Request, internal_id: str):
        return await rental_transition(request, internal_id, action="rent")

    @app.post("/hardware/{internal_id}/return")
    async def return_item(request: Request, internal_id: str):
        return await rental_transition(request, internal_id, action="return")

    @app.get("/admin/audit", response_class=HTMLResponse)
    async def admin_audit(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        records = request.app.state.hardware.all()
        findings = find_issues(records, date.today())
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="audit.html",
            context=_audit_context(
                user=user,
                records=records,
                findings=findings,
                runtime=runtime,
                ai_findings=None,
                warning=None,
            ),
        )

    @app.post("/admin/audit/llm", response_class=HTMLResponse)
    async def admin_llm_audit(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        records = request.app.state.hardware.all()
        findings = find_issues(records, date.today())
        configured, missing = llm_configuration_status(
            runtime.llm_base_url,
            runtime.llm_api_key,
            runtime.llm_model,
        )
        ai_findings = None
        warning = None
        if not configured:
            warning = (
                "DeepSeek audit is unavailable until "
                f"{', '.join(missing)} are configured. "
                "Deterministic findings remain complete."
            )
        else:
            snapshot = build_audit_snapshot(records, findings)
            try:
                ai_findings = request_deepseek_audit(
                    snapshot,
                    base_url=runtime.llm_base_url,
                    api_key=runtime.llm_api_key,
                    model=runtime.llm_model,
                    transport=getattr(request.app.state, "llm_transport", None),
                )
            except AuditUnavailableError:
                warning = (
                    "DeepSeek audit was unavailable or invalid. "
                    "Deterministic findings remain complete."
                )

        return _TEMPLATES.TemplateResponse(
            request=request,
            name="audit.html",
            context=_audit_context(
                user=user,
                records=records,
                findings=findings,
                runtime=runtime,
                ai_findings=ai_findings,
                warning=warning,
            ),
        )

    @app.get("/admin/users", response_class=HTMLResponse)
    async def admin_users(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="admin_users.html",
            context={
                "user": user,
                "users": request.app.state.users.all(),
                "error": None,
                "email": "",
            },
        )

    @app.post("/admin/users", response_class=HTMLResponse)
    async def add_user(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        form = await request.form()
        email = str(form.get("email", ""))
        password = str(form.get("password", ""))
        try:
            create_user(request.app.state.users, email, password)
        except UserInputError as exc:
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="admin_users.html",
                context={
                    "user": user,
                    "users": request.app.state.users.all(),
                    "error": str(exc),
                    "email": email.strip(),
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/admin/hardware/new", response_class=HTMLResponse)
    async def new_hardware(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="hardware_form.html",
            context=_hardware_form_context(
                user=user,
                record=None,
                values=_form_values(),
                error=None,
            ),
        )

    @app.post("/admin/hardware", response_class=HTMLResponse)
    async def add_hardware(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        form = await request.form()
        values = _submitted_values(form)
        try:
            create_hardware(request.app.state.hardware, form)
        except InventoryInputError as exc:
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="hardware_form.html",
                context=_hardware_form_context(
                    user=user,
                    record=None,
                    values=values,
                    error=str(exc),
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/admin/hardware/{internal_id}/edit", response_class=HTMLResponse)
    async def edit_hardware_page(request: Request, internal_id: str):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        record = request.app.state.hardware.get(lambda item: item.get("id") == internal_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="hardware_form.html",
            context=_hardware_form_context(
                user=user,
                record=record,
                values=_form_values(record),
                error=None,
            ),
        )

    @app.post("/admin/hardware/{internal_id}/edit", response_class=HTMLResponse)
    async def edit_hardware(request: Request, internal_id: str):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        record = request.app.state.hardware.get(lambda item: item.get("id") == internal_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        form = await request.form()
        values = _submitted_values(form)
        try:
            updated = update_hardware(
                request.app.state.hardware,
                internal_id,
                form,
                acting_user_id=user["id"],
            )
        except (InventoryInputError, InventoryConflictError) as exc:
            record = request.app.state.hardware.get(lambda item: item.get("id") == internal_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
            response_status = (
                status.HTTP_409_CONFLICT
                if isinstance(exc, InventoryConflictError)
                else status.HTTP_400_BAD_REQUEST
            )
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="hardware_form.html",
                context=_hardware_form_context(
                    user=user,
                    record=record,
                    values=values,
                    error=str(exc),
                ),
                status_code=response_status,
            )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/admin/hardware/{internal_id}/delete")
    async def remove_hardware(request: Request, internal_id: str):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        try:
            removed = delete_hardware(request.app.state.hardware, internal_id)
        except InventoryConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    async def change_repair_status(
        request: Request,
        internal_id: str,
        *,
        expected: str,
        target: str,
    ):
        """Authorize and translate a repair transition result into an HTTP response."""

        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        try:
            record = transition_repair(
                request.app.state.hardware,
                internal_id,
                expected=expected,
                target=target,
            )
        except InventoryConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/admin/hardware/{internal_id}/mark-repair")
    async def mark_repair(request: Request, internal_id: str):
        return await change_repair_status(
            request,
            internal_id,
            expected="Available",
            target="Repair",
        )

    @app.post("/admin/hardware/{internal_id}/clear-repair")
    async def clear_repair(request: Request, internal_id: str):
        return await change_repair_status(
            request,
            internal_id,
            expected="Repair",
            target="Available",
        )

    return app


# ASGI servers import this object via `hardware_hub.app:app`; no process starts here.
app = create_app()
