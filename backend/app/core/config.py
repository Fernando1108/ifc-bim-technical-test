import functools

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    postgres_host: str = "db"
    postgres_internal_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr

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


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
