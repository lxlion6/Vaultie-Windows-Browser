"""Local Windows-only Vaultie login vault encrypted with Windows DPAPI.

Credentials are tied to the logged-in Windows user. No remote services,
master-password files, or browser cookie persistence are required.
"""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlsplit


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi(data, decrypt=False):
    if os.name != "nt":
        raise OSError("Der Passwortspeicher benötigt Windows DPAPI.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, keep = _blob(data)
    destination = DATA_BLOB()
    if decrypt:
        operation = crypt32.CryptUnprotectData
        args = (ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination))
    else:
        operation = crypt32.CryptProtectData
        args = (ctypes.byref(source), "Vaultie Zugangsdaten", None, None, None, 0,
                ctypes.byref(destination))
    if not operation(*args):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def secure_origin(value):
    try:
        url = urlsplit(value)
        if url.scheme.lower() != "https" or not url.hostname or url.username or url.password:
            return None
        host = url.hostname.lower()
        port = url.port
        if port and port != 443:
            return f"https://{host}:{port}"
        return f"https://{host}"
    except ValueError:
        return None


class CredentialVault:
    def __init__(self, path):
        self.path = Path(path)
        self._items = {}
        if self.path.exists():
            # Refuse invalid or undecryptable files, rather than silently replacing them.
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            data = _dpapi(base64.b64decode(raw["encrypted"]), decrypt=True)
            items = json.loads(data.decode("utf-8"))
            if not isinstance(items, dict):
                raise ValueError("Ungültiges Format des Passwortspeichers")
            self._items = items

    def list_entries(self):
        return [(origin, item.get("username", "")) for origin, item
                in sorted(self._items.items())]

    def get(self, origin):
        item = self._items.get(origin)
        if not item:
            return None
        return {"username": item["username"], "password": item["password"]}

    def save(self, origin, username, password):
        if not secure_origin(origin) == origin:
            raise ValueError("Nur sichere HTTPS-Websites dürfen gespeichert werden.")
        if not username or not password:
            raise ValueError("Benutzername und Passwort sind erforderlich.")
        self._items[origin] = {"username": username, "password": password}
        self._flush()

    def remove(self, origin):
        if origin in self._items:
            del self._items[origin]
            self._flush()

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plain = json.dumps(self._items, ensure_ascii=False).encode("utf-8")
        token = base64.b64encode(_dpapi(plain)).decode("ascii")
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "encrypted": token}), encoding="utf-8")
        os.replace(temp, self.path)
