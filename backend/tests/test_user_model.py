import sqlalchemy as sa

from app.models.user import User


def _col(name: str) -> sa.Column:
    return User.__table__.c[name]


def test_tablename():
    assert User.__tablename__ == "users"


def test_expected_columns_exist():
    expected = {"id", "email", "hashed_password", "is_active", "created_at", "updated_at"}
    actual = set(User.__table__.c.keys())
    assert actual == expected


def test_no_plain_password_column():
    columns = set(User.__table__.c.keys())
    assert "password" not in columns
    assert "plain_password" not in columns


def test_email_not_nullable():
    assert _col("email").nullable is False


def test_hashed_password_not_nullable():
    assert _col("hashed_password").nullable is False


def test_unique_constraint_uq_users_email():
    constraint_names = {
        c.name
        for c in User.__table__.constraints
        if isinstance(c, sa.UniqueConstraint)
    }
    assert "uq_users_email" in constraint_names


def test_id_is_primary_key():
    assert _col("id").primary_key is True


def test_is_active_not_nullable():
    assert _col("is_active").nullable is False


def test_created_at_not_nullable():
    assert _col("created_at").nullable is False


def test_updated_at_not_nullable():
    assert _col("updated_at").nullable is False
