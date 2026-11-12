import os
import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import URL


_test_directory = Path(tempfile.mkdtemp(prefix="loyalty-acceptance-"))
_database_url = URL.create(
    "sqlite",
    database=str(_test_directory / "acceptance.sqlite"),
    query={"timeout": "15"},
)
os.environ["DATABASE_URL"] = _database_url.render_as_string(hide_password=False)
os.environ["SECRET_KEY"] = "acceptance-test-key-that-is-not-for-production"

from app import app, db


def _enable_sqlite_foreign_keys(connection, _):
    if connection.__class__.__module__ == "sqlite3":
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


app.config.update(TESTING=True, WTF_CSRF_ENABLED=True, SESSION_COOKIE_SECURE=False)


@pytest.fixture(autouse=True)
def reset_database(request):
    with app.app_context():
        db.session.remove()
        check_foreign_keys = (
            request.node.name == "test_benchmark_append_offsets_ids_and_preserves_existing_rows"
        )
        if check_foreign_keys:
            db.engine.dispose()
            event.listen(db.engine, "connect", _enable_sqlite_foreign_keys)
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()
        if check_foreign_keys:
            event.remove(db.engine, "connect", _enable_sqlite_foreign_keys)
            db.engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def clean_test_database():
    yield
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    shutil.rmtree(_test_directory, ignore_errors=True)
