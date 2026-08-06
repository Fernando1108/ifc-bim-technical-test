import os

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_INTERNAL_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key_only_for_automated_tests_123456")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
