import sqlalchemy as sa

from app.models.ifc_model import IfcModel

_TABLE = IfcModel.__table__


def _col(name: str) -> sa.Column:
    return _TABLE.c[name]


# ---------------------------------------------------------------------------
# Table name
# ---------------------------------------------------------------------------

def test_tablename():
    assert IfcModel.__tablename__ == "ifc_models"


# ---------------------------------------------------------------------------
# Column set
# ---------------------------------------------------------------------------

def test_expected_columns_exist():
    expected = {
        "id",
        "owner_id",
        "original_filename",
        "storage_path",
        "file_size_bytes",
        "sha256",
        "status",
        "ifc_schema",
        "error_message",
        "processing_started_at",
        "processed_at",
        "created_at",
        "updated_at",
    }
    actual = set(_TABLE.c.keys())
    assert actual == expected


# ---------------------------------------------------------------------------
# Primary key
# ---------------------------------------------------------------------------

def test_id_is_primary_key():
    assert _col("id").primary_key is True


# ---------------------------------------------------------------------------
# Non-nullable columns
# ---------------------------------------------------------------------------

def test_owner_id_not_nullable():
    assert _col("owner_id").nullable is False


def test_original_filename_not_nullable():
    assert _col("original_filename").nullable is False


def test_storage_path_not_nullable():
    assert _col("storage_path").nullable is False


def test_file_size_bytes_not_nullable():
    assert _col("file_size_bytes").nullable is False


def test_sha256_not_nullable():
    assert _col("sha256").nullable is False


def test_status_not_nullable():
    assert _col("status").nullable is False


def test_created_at_not_nullable():
    assert _col("created_at").nullable is False


def test_updated_at_not_nullable():
    assert _col("updated_at").nullable is False


# ---------------------------------------------------------------------------
# Nullable columns
# ---------------------------------------------------------------------------

def test_ifc_schema_nullable():
    assert _col("ifc_schema").nullable is True


def test_error_message_nullable():
    assert _col("error_message").nullable is True


def test_processing_started_at_nullable():
    assert _col("processing_started_at").nullable is True


def test_processed_at_nullable():
    assert _col("processed_at").nullable is True


# ---------------------------------------------------------------------------
# Status defaults
# ---------------------------------------------------------------------------

def test_status_default():
    assert _col("status").default.arg == "PENDING"


def test_status_server_default():
    server_default = _col("status").server_default
    assert server_default is not None
    raw = getattr(server_default, "arg", str(server_default))
    assert "PENDING" in str(raw)


# ---------------------------------------------------------------------------
# Foreign key — owner_id → users.id with CASCADE
# ---------------------------------------------------------------------------

def test_owner_id_references_users():
    fks = list(_col("owner_id").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "users"
    assert fk.column.name == "id"


def test_owner_id_fk_ondelete_cascade():
    fks = list(_col("owner_id").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.ondelete.upper() == "CASCADE"


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

def _constraint_names() -> set:
    return {c.name for c in _TABLE.constraints}


def _index_names() -> set:
    return {idx.name for idx in _TABLE.indexes}


def test_unique_constraint_storage_path():
    assert "uq_ifc_models_storage_path" in _constraint_names()


def test_check_constraint_file_size_positive():
    assert "ck_ifc_models_file_size_positive" in _constraint_names()


def test_check_constraint_status():
    assert "ck_ifc_models_status" in _constraint_names()


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

def test_index_owner_id():
    assert "ix_ifc_models_owner_id" in _index_names()


def test_index_status():
    assert "ix_ifc_models_status" in _index_names()


def test_index_sha256():
    assert "ix_ifc_models_sha256" in _index_names()
