import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings

CHUNK_SIZE = 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidIfcFilenameError(Exception):
    pass


class InvalidIfcExtensionError(Exception):
    pass


class EmptyIfcFileError(Exception):
    pass


class IfcFileTooLargeError(Exception):
    pass


class IfcStorageError(Exception):
    pass


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StoredIfcFile:
    original_filename: str
    storage_path: str   # relative filename only, e.g. "<uuid>.ifc"
    file_size_bytes: int
    sha256: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_unlink(path: Path) -> None:
    """Best-effort file removal. Swallows all errors to preserve the main exception."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Filename normalization
# ---------------------------------------------------------------------------

def _normalize_filename(filename: str | None) -> str:
    """
    Validate and normalize an upload filename.

    - Rejects None.
    - Rejects empty or whitespace-only names.
    - Converts backslashes to forward slashes.
    - Returns only the last path component (basename).
    - Rejects an empty basename after extraction.
    - Rejects any extension other than .ifc (case-insensitive).
    """
    if filename is None:
        raise InvalidIfcFilenameError("El nombre del archivo no puede ser nulo.")

    if not filename.strip():
        raise InvalidIfcFilenameError("El nombre del archivo no puede estar vacío.")

    normalized = filename.replace("\\", "/")
    basename = normalized.split("/")[-1]

    if not basename.strip():
        raise InvalidIfcFilenameError("El nombre del archivo resultante está vacío.")

    if Path(basename).suffix.lower() != ".ifc":
        raise InvalidIfcExtensionError(
            "Solo se aceptan archivos con extensión .ifc."
        )

    return basename


# ---------------------------------------------------------------------------
# Storage function
# ---------------------------------------------------------------------------

async def save_ifc_file(upload: UploadFile, settings: Settings) -> StoredIfcFile:
    """
    Validate, store, and return metadata for an uploaded IFC file.

    - Normalizes the filename (basename only, .ifc extension enforced).
    - Creates the storage directory if it does not exist.
    - Writes the file in chunks, enforcing the size limit while writing.
    - Calculates SHA-256 during the write pass.
    - Uses a UUID-based name; the original name is never used in the path.
    - Writes to a .part temp file first, then atomically moves to the final path.
    - Ensures the UploadFile is closed in all exit paths.
    - All filesystem errors are converted to IfcStorageError (with exception chaining).
    - Temporary file cleanup is best-effort: cleanup failures never replace the main exception.

    Raises:
        InvalidIfcFilenameError: filename is None, empty, or path-traversal basename is empty.
        InvalidIfcExtensionError: file extension is not .ifc.
        EmptyIfcFileError: file content is zero bytes.
        IfcFileTooLargeError: file exceeds settings.ifc_max_file_size_bytes.
        IfcStorageError: unexpected filesystem error during mkdir, write, or rename.
    """
    try:
        original_filename = _normalize_filename(upload.filename)

        # Protect mkdir — convert any OS error to IfcStorageError.
        try:
            settings.ifc_storage_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise IfcStorageError(
                "Error al crear el directorio de almacenamiento."
            ) from exc

        file_uuid = uuid.uuid4()
        final_filename = f"{file_uuid}.ifc"
        final_path = settings.ifc_storage_dir / final_filename
        temp_path = settings.ifc_storage_dir / f"{file_uuid}.part"

        hasher = hashlib.sha256()
        total_bytes = 0

        try:
            with open(temp_path, "wb") as fout:
                while True:
                    chunk = await upload.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > settings.ifc_max_file_size_bytes:
                        raise IfcFileTooLargeError(
                            f"El archivo supera el límite de "
                            f"{settings.ifc_max_file_size_mb} MB."
                        )
                    hasher.update(chunk)
                    fout.write(chunk)
        except IfcFileTooLargeError:
            _try_unlink(temp_path)
            raise
        except (InvalidIfcFilenameError, InvalidIfcExtensionError):
            # Defensive — these cannot occur inside this block in practice.
            raise
        except Exception as exc:
            _try_unlink(temp_path)
            raise IfcStorageError("Error al guardar el archivo.") from exc

        if total_bytes == 0:
            _try_unlink(temp_path)
            raise EmptyIfcFileError("El archivo está vacío.")

        try:
            os.replace(temp_path, final_path)
        except Exception as exc:
            _try_unlink(temp_path)
            raise IfcStorageError("Error al publicar el archivo.") from exc

        return StoredIfcFile(
            original_filename=original_filename,
            storage_path=final_filename,
            file_size_bytes=total_bytes,
            sha256=hasher.hexdigest(),
        )

    finally:
        await upload.close()
