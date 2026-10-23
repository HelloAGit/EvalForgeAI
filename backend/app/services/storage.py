"""Persistent artefact storage. Storage keys are generated server-side; clients never supply paths."""
import hashlib
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Tuple

from app.config import settings

_KEY_RE = re.compile(r"^[a-z0-9_-]{1,32}/[0-9a-f-]{36}\.[a-z0-9]{1,8}$")


class StorageError(RuntimeError):
    pass


class LocalArtifactStorage:
    """Filesystem backend rooted at ARTIFACT_DIR (mount a persistent volume there).
    Interface (put_bytes/put_file/path/exists/delete) is small so an object store can replace it."""

    def __init__(self, root: str = None):
        self.root = Path(root or settings.ARTIFACT_DIR).resolve()

    def new_key(self, kind: str, ext: str) -> str:
        key = f"{kind}/{uuid.uuid4()}.{ext}"
        if not _KEY_RE.match(key):
            raise StorageError("invalid storage key")
        return key

    def path(self, key: str) -> Path:
        if not _KEY_RE.match(key):
            raise StorageError("invalid storage key")
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise StorageError("path escapes storage root")
        return p

    def put_file(self, key: str, source: str) -> Tuple[int, str]:
        dest = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = os.path.getsize(source)
        if size > settings.MAX_ARTIFACT_BYTES:
            raise StorageError("artefact exceeds MAX_ARTIFACT_BYTES")
        h = hashlib.sha256()
        with open(source, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        tmp = tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part")
        tmp.close()
        try:
            with open(source, "rb") as src, open(tmp.name, "wb") as dst:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    dst.write(chunk)
            os.replace(tmp.name, dest)  # atomic publish: readers never see partial files
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
        return size, h.hexdigest()

    def put_bytes(self, key: str, data: bytes) -> Tuple[int, str]:
        if len(data) > settings.MAX_ARTIFACT_BYTES:
            raise StorageError("artefact exceeds MAX_ARTIFACT_BYTES")
        dest = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part")
        try:
            tmp.write(data)
            tmp.close()
            os.replace(tmp.name, dest)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
        return len(data), hashlib.sha256(data).hexdigest()

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def delete(self, key: str) -> None:
        try:
            self.path(key).unlink()
        except FileNotFoundError:
            pass


def get_storage() -> LocalArtifactStorage:
    return LocalArtifactStorage()
