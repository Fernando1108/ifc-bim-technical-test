"""
Tests for the IFC storage service.

All tests operate on tmp_path — no real repository storage is touched.
No PostgreSQL connection is made.
"""
import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.ifc_storage import (
    CHUNK_SIZE,
    EmptyIfcFileError,
    IfcFileTooLargeError,
    IfcStorageError,
    InvalidIfcExtensionError,
    InvalidIfcFilenameError,
    _normalize_filename,
    save_ifc_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeUploadFile:
    """Minimal async upload file stub."""

    def __init__(self, filename: str | None, content: bytes) -> None:
        self.filename = filename
        self._content = content
        self._pos = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        if size == -1:
            chunk = self._content[self._pos:]
            self._pos = len(self._content)
        else:
            chunk = self._content[self._pos : self._pos + size]
            self._pos += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def _make_settings(storage_dir: Path, max_mb: int = 50) -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password="test_password_local",
        jwt_secret_key="test_jwt_secret_key_for_storage_tests",
        ifc_storage_dir=storage_dir,
        ifc_max_file_size_mb=max_mb,
    )


def _run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


SAMPLE_CONTENT = b"ISO-10303-21;\nHEADER;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


# ---------------------------------------------------------------------------
# 1. Archivo .ifc válido se almacena
# ---------------------------------------------------------------------------

def test_valid_ifc_stored(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    assert result.original_filename == "model.ifc"
    assert result.file_size_bytes == len(SAMPLE_CONTENT)


# ---------------------------------------------------------------------------
# 2. .IFC también se acepta
# ---------------------------------------------------------------------------

def test_uppercase_extension_accepted(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("MODEL.IFC", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    assert result.original_filename == "MODEL.IFC"


# ---------------------------------------------------------------------------
# 3. Path traversal no controla la ruta final
# ---------------------------------------------------------------------------

def test_path_traversal_does_not_control_final_path(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("../../etc/passwd.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    stored_path = settings.ifc_storage_dir / result.storage_path
    assert stored_path.parent.resolve() == settings.ifc_storage_dir.resolve()


# ---------------------------------------------------------------------------
# 4. Nombre normalizado conserva solamente basename
# ---------------------------------------------------------------------------

def test_normalized_name_is_basename_only(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("folder/subfolder/model.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    assert result.original_filename == "model.ifc"
    assert "/" not in result.original_filename
    assert "\\" not in result.original_filename


# ---------------------------------------------------------------------------
# 5. Extensión inválida se rechaza
# ---------------------------------------------------------------------------

def test_invalid_extension_rejected(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.txt", SAMPLE_CONTENT)
    with pytest.raises(InvalidIfcExtensionError):
        _run(save_ifc_file(upload, settings))


# ---------------------------------------------------------------------------
# 6. model.ifc.exe se rechaza
# ---------------------------------------------------------------------------

def test_double_extension_exe_rejected(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc.exe", SAMPLE_CONTENT)
    with pytest.raises(InvalidIfcExtensionError):
        _run(save_ifc_file(upload, settings))


# ---------------------------------------------------------------------------
# 7. Filename vacío se rechaza
# ---------------------------------------------------------------------------

def test_empty_filename_rejected(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("", SAMPLE_CONTENT)
    with pytest.raises(InvalidIfcFilenameError):
        _run(save_ifc_file(upload, settings))


def test_none_filename_rejected(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile(None, SAMPLE_CONTENT)
    with pytest.raises(InvalidIfcFilenameError):
        _run(save_ifc_file(upload, settings))


# ---------------------------------------------------------------------------
# 8. Archivo vacío se rechaza
# ---------------------------------------------------------------------------

def test_empty_file_rejected(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", b"")
    with pytest.raises(EmptyIfcFileError):
        _run(save_ifc_file(upload, settings))


# ---------------------------------------------------------------------------
# 9. Archivo sobre límite se rechaza
# ---------------------------------------------------------------------------

def test_file_over_limit_rejected(tmp_path):
    settings = _make_settings(tmp_path, max_mb=1)
    oversized = b"x" * (1024 * 1024 + 1)
    upload = FakeUploadFile("model.ifc", oversized)
    with pytest.raises(IfcFileTooLargeError):
        _run(save_ifc_file(upload, settings))


# ---------------------------------------------------------------------------
# 10. Archivo demasiado grande no deja .part
# ---------------------------------------------------------------------------

def test_oversized_file_no_part_file(tmp_path):
    settings = _make_settings(tmp_path, max_mb=1)
    oversized = b"x" * (1024 * 1024 + 1)
    upload = FakeUploadFile("model.ifc", oversized)
    with pytest.raises(IfcFileTooLargeError):
        _run(save_ifc_file(upload, settings))
    part_files = list(settings.ifc_storage_dir.glob("*.part"))
    assert len(part_files) == 0


# ---------------------------------------------------------------------------
# 11. Archivo demasiado grande no deja .ifc final
# ---------------------------------------------------------------------------

def test_oversized_file_no_ifc_final(tmp_path):
    settings = _make_settings(tmp_path, max_mb=1)
    oversized = b"x" * (1024 * 1024 + 1)
    upload = FakeUploadFile("model.ifc", oversized)
    with pytest.raises(IfcFileTooLargeError):
        _run(save_ifc_file(upload, settings))
    ifc_files = list(settings.ifc_storage_dir.glob("*.ifc"))
    assert len(ifc_files) == 0


# ---------------------------------------------------------------------------
# 12. SHA-256 coincide con hashlib
# ---------------------------------------------------------------------------

def test_sha256_matches(tmp_path):
    settings = _make_settings(tmp_path)
    content = b"IFC content for sha256 test"
    expected = hashlib.sha256(content).hexdigest()
    upload = FakeUploadFile("model.ifc", content)
    result = _run(save_ifc_file(upload, settings))
    assert result.sha256 == expected


# ---------------------------------------------------------------------------
# 13. file_size_bytes coincide con bytes reales
# ---------------------------------------------------------------------------

def test_file_size_bytes_correct(tmp_path):
    settings = _make_settings(tmp_path)
    content = b"A" * 1234
    upload = FakeUploadFile("model.ifc", content)
    result = _run(save_ifc_file(upload, settings))
    assert result.file_size_bytes == 1234


# ---------------------------------------------------------------------------
# 14. storage_path es relativo
# ---------------------------------------------------------------------------

def test_storage_path_is_relative(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    path = Path(result.storage_path)
    assert not path.is_absolute()
    assert path.name == result.storage_path
    assert len(path.parts) == 1


# ---------------------------------------------------------------------------
# 15. Archivo final existe
# ---------------------------------------------------------------------------

def test_final_file_exists(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    final = settings.ifc_storage_dir / result.storage_path
    assert final.exists()


# ---------------------------------------------------------------------------
# 16. Archivo .part desaparece después de éxito
# ---------------------------------------------------------------------------

def test_no_part_file_after_success(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    _run(save_ifc_file(upload, settings))
    part_files = list(settings.ifc_storage_dir.glob("*.part"))
    assert len(part_files) == 0


# ---------------------------------------------------------------------------
# 17. Filename generado tiene sufijo .ifc
# ---------------------------------------------------------------------------

def test_generated_filename_has_ifc_suffix(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    assert result.storage_path.endswith(".ifc")


# ---------------------------------------------------------------------------
# 18. Filename generado corresponde a UUID válido
# ---------------------------------------------------------------------------

def test_generated_filename_is_valid_uuid(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    result = _run(save_ifc_file(upload, settings))
    stem = Path(result.storage_path).stem
    # Will raise ValueError if not a valid UUID
    parsed = uuid.UUID(stem)
    assert str(parsed) == stem


# ---------------------------------------------------------------------------
# 19. UploadFile queda cerrado tras éxito
# ---------------------------------------------------------------------------

def test_upload_closed_after_success(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)
    _run(save_ifc_file(upload, settings))
    assert upload.closed is True


# ---------------------------------------------------------------------------
# 20. UploadFile queda cerrado tras error
# ---------------------------------------------------------------------------

def test_upload_closed_after_error(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", b"")  # empty → EmptyIfcFileError
    with pytest.raises(EmptyIfcFileError):
        _run(save_ifc_file(upload, settings))
    assert upload.closed is True


def test_upload_closed_after_extension_error(tmp_path):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.txt", SAMPLE_CONTENT)
    with pytest.raises(InvalidIfcExtensionError):
        _run(save_ifc_file(upload, settings))
    assert upload.closed is True


def test_upload_closed_after_too_large(tmp_path):
    settings = _make_settings(tmp_path, max_mb=1)
    upload = FakeUploadFile("model.ifc", b"x" * (1024 * 1024 + 1))
    with pytest.raises(IfcFileTooLargeError):
        _run(save_ifc_file(upload, settings))
    assert upload.closed is True


# ---------------------------------------------------------------------------
# _normalize_filename unit tests
# ---------------------------------------------------------------------------

def test_normalize_simple():
    assert _normalize_filename("model.ifc") == "model.ifc"


def test_normalize_forward_slash():
    assert _normalize_filename("folder/model.ifc") == "model.ifc"


def test_normalize_backslash():
    assert _normalize_filename("..\\..\\secret.ifc") == "secret.ifc"


def test_normalize_absolute():
    assert _normalize_filename("/tmp/test.ifc") == "test.ifc"


def test_normalize_mixed_case():
    assert _normalize_filename("building.IfC") == "building.IfC"


# ---------------------------------------------------------------------------
# mkdir failure — raises IfcStorageError, never raw OSError, upload closed
# ---------------------------------------------------------------------------

def test_mkdir_failure_raises_ifc_storage_error(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)

    def _failing_mkdir(self, *args, **kwargs):
        raise PermissionError("Permission denied: /app/storage")

    monkeypatch.setattr("pathlib.Path.mkdir", _failing_mkdir)

    with pytest.raises(IfcStorageError):
        _run(save_ifc_file(upload, settings))


def test_mkdir_failure_does_not_leak_permission_error(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)

    def _failing_mkdir(self, *args, **kwargs):
        raise PermissionError("Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _failing_mkdir)

    with pytest.raises(IfcStorageError):
        _run(save_ifc_file(upload, settings))
    # If we reach here, PermissionError was NOT propagated raw. ✓


def test_mkdir_failure_upload_closed(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path)
    upload = FakeUploadFile("model.ifc", SAMPLE_CONTENT)

    def _failing_mkdir(self, *args, **kwargs):
        raise PermissionError("Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _failing_mkdir)

    with pytest.raises(IfcStorageError):
        _run(save_ifc_file(upload, settings))

    assert upload.closed is True
