"""Access control.

Deployments:
- Mac (default): requests from this machine are trusted (OPENRUN_TRUST_LOCAL=1); other devices on the
  wifi need the PIN/password.
- Public server (VPS behind a reverse proxy): OPENRUN_TRUST_LOCAL=0 and OPENRUN_TRUST_PROXY=1. Every
  request needs a session (password login) or the API token (MCP / scripts). Behind a proxy all
  traffic arrives from the proxy's address, so "local" must never be trusted there.

Sessions are HMAC-signed, expire after 90 days and are bound to the current password: changing it
logs every device out. Login attempts are rate limited per real client IP.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import Request

COOKIE = "openrun_session"
SESSION_DAYS = 90
MIN_PUBLIC_PASSWORD = 12


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


PASSWORD = _env("OPENRUN_PASSWORD") or _env("OPENRUN_PIN")
TRUST_LOCAL = _env("OPENRUN_TRUST_LOCAL", "1") == "1"
TRUST_PROXY = _env("OPENRUN_TRUST_PROXY", "0") == "1"
API_TOKEN = _env("OPENRUN_API_TOKEN")


def _server_secret() -> bytes:
    if _env("OPENRUN_SECRET"):
        return _env("OPENRUN_SECRET").encode()
    path = Path(_env("OPENRUN_DATA", str(Path.home() / ".openrun"))) / "secret.key"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(secrets.token_hex(32))
            path.chmod(0o600)
        return path.read_text().strip().encode()
    except OSError:
        return secrets.token_hex(32).encode()  # sessions won't survive a restart, still safe


_KEY = hashlib.sha256(_server_secret() + b"|" + PASSWORD.encode()).digest()
_fails: dict[str, list[float]] = {}


def check_config() -> None:
    """Refuse to run publicly with a weak or missing password."""
    if not TRUST_LOCAL and len(PASSWORD) < MIN_PUBLIC_PASSWORD:
        raise RuntimeError(f"OPENRUN_PASSWORD debe tener al menos {MIN_PUBLIC_PASSWORD} caracteres en un servidor público")
    if API_TOKEN and len(API_TOKEN) < 32:
        raise RuntimeError("OPENRUN_API_TOKEN debe tener al menos 32 caracteres")


def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def is_https(request: Request) -> bool:
    if TRUST_PROXY and request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return request.url.scheme == "https"


def is_local(request: Request) -> bool:
    if not TRUST_LOCAL or (TRUST_PROXY and request.headers.get("x-forwarded-for")):
        return False
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") or host.startswith("::ffff:127.")


def make_session() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"iat": int(time.time())}).encode()).decode().rstrip("=")
    sig = hmac.new(_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def valid_session(token: str) -> bool:
    if not PASSWORD or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(_KEY, payload.encode(), hashlib.sha256).hexdigest()):
        return False
    try:
        iat = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["iat"]
    except (ValueError, KeyError):
        return False
    return 0 <= time.time() - iat <= SESSION_DAYS * 86400


def authed(request: Request) -> bool:
    if is_local(request):
        return True
    bearer = request.headers.get("authorization", "")
    if API_TOKEN and bearer.lower().startswith("bearer ") and hmac.compare_digest(bearer[7:].strip(), API_TOKEN):
        return True
    return valid_session(request.cookies.get(COOKIE, ""))


def check_password(request: Request, given: str) -> tuple[bool, str | None]:
    """Returns (ok, error). 10 failures per IP in 10 minutes -> locked for the rest of the window."""
    ip = client_ip(request)
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 600]
    if len(recent) >= 10:
        return False, "Demasiados intentos. Espera 10 minutos."
    if not PASSWORD or not hmac.compare_digest(given.strip().encode(), PASSWORD.encode()):
        _fails[ip] = recent + [now]
        time.sleep(1)
        return False, "Contraseña incorrecta" if len(PASSWORD) > 6 else "PIN incorrecto"
    _fails.pop(ip, None)
    return True, None
