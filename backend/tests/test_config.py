import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import URL

from app.core.config import Settings

_JWT_SECRET = "test_jwt_secret_key_only_for_tests_123456"


def _make_settings(**kwargs) -> Settings:
    defaults = {
        "postgres_host": "db",
        "postgres_internal_port": 5432,
        "postgres_db": "test_db",
        "postgres_user": "test_user",
        "postgres_password": "prueba@local:123/segura",
        "jwt_secret_key": _JWT_SECRET,
        "access_token_expire_minutes": 30,
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


def test_jwt_secret_key_is_secret_str():
    settings = _make_settings()
    assert isinstance(settings.jwt_secret_key, SecretStr)


def test_jwt_secret_key_get_secret_value():
    settings = _make_settings(jwt_secret_key=_JWT_SECRET)
    assert settings.jwt_secret_key.get_secret_value() == _JWT_SECRET


def test_access_token_expire_minutes_accepts_positive():
    settings = _make_settings(access_token_expire_minutes=60)
    assert settings.access_token_expire_minutes == 60


def test_access_token_expire_minutes_rejects_zero():
    with pytest.raises(ValidationError):
        _make_settings(access_token_expire_minutes=0)


def test_access_token_expire_minutes_rejects_negative():
    with pytest.raises(ValidationError):
        _make_settings(access_token_expire_minutes=-1)


# ---------------------------------------------------------------------------
# IFC storage configuration
# ---------------------------------------------------------------------------

def test_ifc_storage_dir_default():
    from pathlib import Path
    settings = _make_settings()
    assert settings.ifc_storage_dir == Path("/app/storage")


def test_ifc_max_file_size_mb_default():
    settings = _make_settings()
    assert settings.ifc_max_file_size_mb == 50


def test_ifc_max_file_size_bytes_50mb():
    settings = _make_settings()
    assert settings.ifc_max_file_size_bytes == 52428800


def test_ifc_max_file_size_bytes_10mb():
    settings = _make_settings(ifc_max_file_size_mb=10)
    assert settings.ifc_max_file_size_bytes == 10485760


def test_ifc_max_file_size_mb_rejects_zero():
    with pytest.raises(ValidationError):
        _make_settings(ifc_max_file_size_mb=0)


def test_ifc_max_file_size_mb_rejects_negative():
    with pytest.raises(ValidationError):
        _make_settings(ifc_max_file_size_mb=-1)


def test_ifc_max_file_size_mb_rejects_above_max():
    with pytest.raises(ValidationError):
        _make_settings(ifc_max_file_size_mb=51)
