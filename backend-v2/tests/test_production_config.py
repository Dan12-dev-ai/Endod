"""Configuration that must hold in production."""

import pytest


def test_environment_is_case_insensitive(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", " Production ")
    assert Settings().ENVIRONMENT == "production"


def test_database_url_from_settings_is_used(monkeypatch):
    from app.core.config import get_settings
    from dedan_platform import db

    monkeypatch.delenv("DEDAN_DATABASE_URL", raising=False)
    monkeypatch.setattr(get_settings(), "DEDAN_DATABASE_URL", "postgresql+psycopg://u:p@db/dedan")
    assert db.database_url() == "postgresql+psycopg://u:p@db/dedan"


def test_production_refuses_the_sqlite_fallback(monkeypatch):
    from app.core.config import get_settings
    from dedan_platform import db

    monkeypatch.delenv("DEDAN_DATABASE_URL", raising=False)
    monkeypatch.setattr(get_settings(), "DEDAN_DATABASE_URL", None)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(db.DatabaseNotConfiguredError):
        db.database_url()


def test_development_keeps_the_sqlite_default(monkeypatch):
    from app.core.config import get_settings
    from dedan_platform import db

    monkeypatch.delenv("DEDAN_DATABASE_URL", raising=False)
    monkeypatch.setattr(get_settings(), "DEDAN_DATABASE_URL", None)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert db.database_url() == db.DEFAULT_DATABASE_URL


def test_postgres_engine_can_be_built(monkeypatch):
    """The driver is installed and the pool arguments are valid (no connection)."""
    from dedan_platform import db

    monkeypatch.setenv("DEDAN_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/dedan")
    db.reset_engine()
    try:
        engine = db.get_engine()
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
    finally:
        db.reset_engine()


def test_production_refuses_a_sqlite_url(monkeypatch):
    from dedan_platform import db

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEDAN_DATABASE_URL", "sqlite:///./dedan_platform.db")
    monkeypatch.delenv("DEDAN_ALLOW_SQLITE_IN_PRODUCTION", raising=False)
    with pytest.raises(db.DatabaseNotConfiguredError):
        db.database_url()


def test_single_node_demo_can_opt_in_to_sqlite(monkeypatch):
    from dedan_platform import db

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEDAN_DATABASE_URL", "sqlite:////data/dedan.db")
    monkeypatch.setenv("DEDAN_ALLOW_SQLITE_IN_PRODUCTION", "true")
    assert db.database_url() == "sqlite:////data/dedan.db"


def test_allowed_hosts_come_from_settings(monkeypatch):
    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    from fastapi.testclient import TestClient

    import main_clinical
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={
        "ENVIRONMENT": "production", "DEBUG": False, "ALLOWED_HOSTS": ["backend", "localhost"],
        "ADMIN_API_KEY": "test-admin-key",
    })
    client = TestClient(main_clinical.create_app(settings), base_url="http://backend")
    assert client.get("/health").status_code == 200
    other = TestClient(main_clinical.create_app(settings), base_url="http://evil.example")
    assert other.get("/health").status_code == 400
