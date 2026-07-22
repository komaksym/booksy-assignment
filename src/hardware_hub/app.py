"""FastAPI composition and HTTP routes for the shell/authentication slice."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
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
from hardware_hub.inventory import import_seed

_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60


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
    async def home(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="home.html",
            context={"user": user},
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

    return app


# ASGI servers import this object via `hardware_hub.app:app`; no process starts here.
app = create_app()
