"""User-entered display emails, encrypted for the current Windows account."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import tempfile


EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\Z")
LABELS = {"유튜브1", "유튜브2", "유튜브3"}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise ValueError("PROFILE_EMAIL_ENCRYPTION_UNAVAILABLE")
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.windll.crypt32
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    if not ok:
        raise ValueError("PROFILE_EMAIL_DECRYPT_FAILED" if decrypt else "PROFILE_EMAIL_ENCRYPT_FAILED")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


class ProfileEmails:
    def __init__(self, path: Path, labels=LABELS):
        self.path = path
        self.labels = frozenset(labels)

    def get(self, label: str) -> str:
        if label not in self.labels:
            raise ValueError("PROFILE_SETTINGS_INVALID")
        if self.path.is_symlink():
            raise ValueError("PROFILE_EMAIL_FILE_UNSAFE")
        if not self.path.exists():
            return ""
        if self.path.stat().st_size > 8192:
            raise ValueError("PROFILE_EMAIL_FILE_INVALID")
        try:
            saved = json.loads(self.path.read_text(encoding="ascii"))
            cipher = saved.get(label, "")
            return _dpapi(base64.b64decode(cipher, validate=True), decrypt=True).decode("utf-8") if cipher else ""
        except (ValueError, UnicodeError, TypeError, AttributeError) as exc:
            raise ValueError("PROFILE_EMAIL_FILE_INVALID") from exc

    def set(self, label: str, email: str) -> None:
        if label not in self.labels or not isinstance(email, str) or len(email) > 254 or (email and not EMAIL.fullmatch(email)):
            raise ValueError("PROFILE_EMAIL_INVALID")
        if self.path.is_symlink():
            raise ValueError("PROFILE_EMAIL_FILE_UNSAFE")
        saved = {}
        if self.path.exists():
            if self.path.stat().st_size > 8192:
                raise ValueError("PROFILE_EMAIL_FILE_INVALID")
            saved = json.loads(self.path.read_text(encoding="ascii"))
            if not isinstance(saved, dict) or any(key not in self.labels or not isinstance(value, str) for key, value in saved.items()):
                raise ValueError("PROFILE_EMAIL_FILE_INVALID")
        if email:
            saved[label] = base64.b64encode(_dpapi(email.encode("utf-8"))).decode("ascii")
        else:
            saved.pop(label, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="emails-", suffix=".tmp", dir=self.path.parent)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                json.dump(saved, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
