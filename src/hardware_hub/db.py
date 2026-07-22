"""TinyDB lifecycle helpers."""

from pathlib import Path

from tinydb import TinyDB
from tinydb.table import Table


def open_db(path: Path) -> TinyDB:
    """Open the configured database after ensuring its parent exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(path, ensure_ascii=False, indent=2)


def users_table(db: TinyDB) -> Table:
    """Return the users table used by the authentication slice."""

    return db.table("users")
