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
from hardware_hub.rules import Finding, find_issues

_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
_ORIGINAL_SOURCE_COUNT = 11


def _dashboard_context(
    *,
    user: dict[str, Any],
    all_records: list[dict[str, Any]],
    records: list[dict[str, Any]],
    filters: dict[str, str],
    error: str | None,
) -> dict[str, Any]:
    """Build template-ready dashboard state without mutating stored hardware.

    ``all_records`` drives global brands and administrator finding totals, while
    ``records`` is the already filtered and sorted subset rendered in the table.
    Each table row is copied before presentation-only findings and repair actions
    are attached.
    """

    findings = find_issues(all_records, date.today()) if user["role"] == "admin" else ()
    by_hardware: dict[str, list[Finding]] = {}
    for finding in findings:
        by_hardware.setdefault(finding.hardware_id, []).append(finding)

    rows = []
    for record in records:
        row = dict(record)
        row["findings"] = by_hardware.get(str(record["id"]), [])
        row["repair_action"] = (
            "mark-repair"
            if record.get("holder_user_id") is None and record.get("status") == "Available"
            else "clear-repair"
            if record.get("holder_user_id") is None and record.get("status") == "Repair"
            else None
        )
        rows.append(row)

    brands = sorted(
        {
            str(record["brand"])
            for record in all_records
            if isinstance(record.get("brand"), str) and record["brand"]
        },
        key=str.casefold,
    )
    return {
        "user": user,
        "records": rows,
        "filters": filters,
        "brands": brands,
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
    if record is not None and record.get("holder_user_id") is None:
        if record.get("status") == "Available":
            repair_action = "mark-repair"
        elif record.get("status") == "Repair":
            repair_action = "clear-repair"
    return {
        "user": user,
        "record": record,
        "values": values,
        "error": error,
        "original_import": _original_import(record) if record is not None else [],
        "repair_action": repair_action,
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
                all_records=all_records if user["role"] == "admin" else visible,
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
            updated = update_hardware(request.app.state.hardware, internal_id, form)
        except (InventoryInputError, InventoryConflictError) as exc:
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
