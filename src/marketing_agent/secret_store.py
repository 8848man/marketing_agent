"""Windows DPAPI-backed secret file; other platforms keep using the 0600 .env file."""

from __future__ import annotations

import base64
import binascii
import ctypes
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

STORE_MAX_BYTES = 65_536
SECRET_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
CRYPTPROTECT_UI_FORBIDDEN = 0x1
DPAPI_ENTROPY = b"marketing_agent/v1"


class DpapiFileStore:
    """JSON file of base64 ciphertexts; encryption functions are injected."""

    def __init__(self, path: str | Path, protect: Callable[[bytes], bytes],
                 unprotect: Callable[[bytes], bytes]):
        self.path = Path(path)
        self._protect = protect
        self._unprotect = unprotect

    def _load(self) -> dict[str, str]:
        if self.path.is_symlink():
            raise ValueError("SECRET_STORE_INVALID")
        if not self.path.exists():
            return {}
        if not self.path.is_file() or self.path.stat().st_size > STORE_MAX_BYTES:
            raise ValueError("SECRET_STORE_INVALID")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("SECRET_STORE_INVALID") from exc
        secrets = data.get("secrets") if isinstance(data, dict) else None
        if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(secrets, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in secrets.items())):
            raise ValueError("SECRET_STORE_INVALID")
        return secrets

    def _save(self, secrets: dict[str, str]) -> None:
        text = json.dumps({"version": 1, "secrets": secrets}, sort_keys=True)
        if len(text.encode("utf-8")) > STORE_MAX_BYTES:
            raise ValueError("SECRET_STORE_INVALID")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="secrets-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _check_name(name: str) -> None:
        if not isinstance(name, str) or not SECRET_NAME.match(name):
            raise ValueError("SECRET_STORE_INVALID")

    def names(self) -> list[str]:
        return sorted(self._load())

    def get(self, name: str) -> str | None:
        self._check_name(name)
        encoded = self._load().get(name)
        if encoded is None:
            return None
        try:
            return self._unprotect(base64.b64decode(encoded, validate=True)).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("SECRET_STORE_INVALID") from exc
        except OSError as exc:
            raise ValueError("SECRET_STORE_UNREADABLE") from exc

    def set(self, name: str, value: str) -> None:
        self._check_name(name)
        if not isinstance(value, str) or not value:
            raise ValueError("SECRET_STORE_INVALID")
        secrets = self._load()
        secrets[name] = base64.b64encode(self._protect(value.encode("utf-8"))).decode("ascii")
        self._save(secrets)

    def delete(self, name: str) -> None:
        self._check_name(name)
        secrets = self._load()
        if secrets.pop(name, None) is not None:
            self._save(secrets)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _call_dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI_UNAVAILABLE")
    from ctypes import wintypes

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(_DataBlob),
                         ctypes.c_wchar_p if protect else ctypes.POINTER(wintypes.LPWSTR),
                         ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    function.restype = wintypes.BOOL
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(DPAPI_ENTROPY)
    output = _DataBlob()
    description = wintypes.LPWSTR()
    description_arg = "marketing_agent" if protect else ctypes.byref(description)
    ok = function(ctypes.byref(source), description_arg, ctypes.byref(entropy), None, None,
                  CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output))
    if not protect and description:
        kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))
    if not ok:
        raise OSError("DPAPI_FAILED")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
        del source_buffer, entropy_buffer


def dpapi_protect(data: bytes) -> bytes:
    return _call_dpapi(data, True)


def dpapi_unprotect(data: bytes) -> bytes:
    return _call_dpapi(data, False)


def default_store(app_root: Path) -> DpapiFileStore | None:
    if os.name != "nt":
        return None
    return DpapiFileStore(Path(app_root) / "data" / "dashboard" / "secrets.dpapi.json",
                          dpapi_protect, dpapi_unprotect)
