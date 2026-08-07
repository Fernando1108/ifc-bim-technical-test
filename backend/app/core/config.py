import functools
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    postgres_host: str = "db"
    postgres_internal_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr

    jwt_secret_key: SecretStr
    access_token_expire_minutes: int = Field(default=30, gt=0)

    ifc_storage_dir: Path = Path("/app/storage")
    ifc_max_file_size_mb: int = Field(default=50, gt=0, le=50)

    model_config = {"extra": "ignore"}

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_internal_port,
            database=self.postgres_db,
        )

    @property
    def ifc_max_file_size_bytes(self) -> int:
        return self.ifc_max_file_size_mb * 1024 * 1024


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
