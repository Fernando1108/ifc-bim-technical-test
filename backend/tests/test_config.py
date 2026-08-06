from pydantic import SecretStr
from sqlalchemy.engine import URL

from app.core.config import Settings


def _make_settings(**kwargs) -> Settings:
    defaults = {
        "postgres_db": "test_db",
        "postgres_user": "test_user",
        "postgres_password": "prueba@local:123/segura",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def test_database_url_drivername():
    settings = _make_settings()
    assert settings.database_url.drivername == "postgresql+psycopg"


def test_database_url_username():
    settings = _make_settings(postgres_user="myuser")
    assert settings.database_url.username == "myuser"


def test_database_url_host_default():
    settings = _make_settings()
    assert settings.database_url.host == "db"


def test_database_url_port_default():
    settings = _make_settings()
    assert settings.database_url.port == 5432


def test_database_url_database():
    settings = _make_settings(postgres_db="mydb")
    assert settings.database_url.database == "mydb"


def test_database_url_preserves_special_chars_in_password():
    raw = "prueba@local:123/segura"
    settings = _make_settings(postgres_password=raw)
    rendered: URL = settings.database_url
    assert rendered.password == raw


def test_secret_str_does_not_expose_password():
    settings = _make_settings(postgres_password="super_secret")
    secret: SecretStr = settings.postgres_password
    assert "super_secret" not in repr(secret)
    assert "super_secret" not in str(secret)
