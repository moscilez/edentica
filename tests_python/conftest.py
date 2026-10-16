"""Integration tests always use a fresh, separate PostgreSQL database."""
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")


@pytest.fixture(scope="session")
def postgres_url():
    settings = conninfo_to_dict(os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"])
    name = "edentica_test_" + uuid4().hex
    settings["dbname"] = "postgres"
    admin_url = make_conninfo(**settings)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
    settings["dbname"] = name
    # Use URI so the application can validate the PostgreSQL scheme.
    from urllib.parse import quote
    url = f"postgresql://{quote(settings['user'])}:{quote(settings.get('password',''), safe='')}@{settings.get('host','localhost')}:{settings.get('port','5432')}/{name}"
    try:
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def client(postgres_url):
    from backend.app import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(postgres_url), base_url="http://localhost") as test_client:
        yield test_client
