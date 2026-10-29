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

from .i18n import _

COOKIE = "openrun_session"
SESSION_DAYS = 90
MIN_PUBLIC_PASSWORD = 12


def too_many_attempts() -> str:
    return _("Too many attempts. Wait 10 minutes.")


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


_SECRET = _server_secret()
_fails: dict[str, list[float]] = {}
MIN_USER_PASSWORD = 10
OPEN_SIGNUP = _env("OPENRUN_OPEN_SIGNUP", "0") == "1"
ADMIN_USERNAME = _env("OPENRUN_ADMIN_USER", "admin").lower()


def check_config() -> None:
    """Refuse to run publicly with a weak or missing bootstrap password."""
    if not TRUST_LOCAL and len(PASSWORD) < MIN_PUBLIC_PASSWORD:
        raise RuntimeError(f"OPENRUN_PASSWORD must be at least {MIN_PUBLIC_PASSWORD} characters on a public server")
    if API_TOKEN and len(API_TOKEN) < 32:
        raise RuntimeError("OPENRUN_API_TOKEN must be at least 32 characters")


# ---------------------------------------------------------------- passwords


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _scheme, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def password_problem(pw: str) -> str | None:
    if len(pw) < MIN_USER_PASSWORD:
        return _("The password must be at least {n} characters", n=MIN_USER_PASSWORD)
    return None


# ---------------------------------------------------------------- users


def _db():
    from sqlmodel import Session

    from .db import engine
    return Session(engine)


def get_user(uid: int):
    from .db import User
    with _db() as s:
        return s.get(User, uid)


def ensure_admin() -> None:
    """First start: create the admin account (user 1, owner of pre-multi-user data) from the
    bootstrap password (OPENRUN_PASSWORD / OPENRUN_PIN). Later password changes happen in the app."""
    from sqlmodel import select

    from .db import User
    with _db() as s:
        if s.exec(select(User)).first():
            return
        s.add(User(id=1, username=ADMIN_USERNAME, name="Admin", is_admin=True,
                   password_hash=hash_password(PASSWORD) if PASSWORD else "",
                   created_at=time.strftime("%Y-%m-%dT%H:%M:%S")))
        s.commit()


def find_user(username: str):
    from sqlmodel import select

    from .db import User
    with _db() as s:
        return s.exec(select(User).where(User.username == username.strip().lower())).first()


# ---------------------------------------------------------------- requests


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


def _key(uid: int, pw_hash: str) -> bytes:
    # bound to the user's password: changing it logs out every device of that user
    return hashlib.sha256(_SECRET + f"|{uid}|".encode() + pw_hash.encode()).digest()


def make_session(user) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"uid": user.id, "iat": int(time.time())}).encode()).decode().rstrip("=")
    sig = hmac.new(_key(user.id, user.password_hash), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def session_user(token: str) -> int | None:
    if "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        uid, iat = int(data["uid"]), data["iat"]
    except (ValueError, KeyError, TypeError):
        return None
    user = get_user(uid)
    if not user or not user.password_hash:
        return None
    if not hmac.compare_digest(sig, hmac.new(_key(uid, user.password_hash), payload.encode(), hashlib.sha256).hexdigest()):
        return None
    return uid if 0 <= time.time() - iat <= SESSION_DAYS * 86400 else None


TOKEN_PREFIX = "or_"


def token_hash(token: str) -> str:
    # tokens are 32 random bytes: a fast hash is enough (nothing to brute-force)
    return hashlib.sha256(token.encode()).hexdigest()


def _session():
    from sqlmodel import Session

    from .db import engine
    return Session(engine)


def new_personal_token(uid: int) -> str:
    """Create (or replace) the user's personal API token; returned once, only its hash is stored."""
    from .db import User
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with _session() as s:
        u = s.get(User, uid)
        u.api_token_hash = token_hash(token)
        s.add(u)
        s.commit()
    return token


def revoke_personal_token(uid: int) -> None:
    from .db import User
    with _session() as s:
        u = s.get(User, uid)
        u.api_token_hash = None
        s.add(u)
        s.commit()


def token_user(token: str) -> int | None:
    if API_TOKEN and hmac.compare_digest(token, API_TOKEN):
        return 1  # server-wide token from the environment acts as the admin
    if not token.startswith(TOKEN_PREFIX):
        return None
    from sqlmodel import select

    from .db import User
    with _session() as s:
        u = s.exec(select(User).where(User.api_token_hash == token_hash(token))).first()
    return u.id if u else None


def request_user(request: Request) -> int | None:
    """User id of the request: session cookie, API token (personal or the admin's) or this machine (admin)."""
    uid = session_user(request.cookies.get(COOKIE, ""))
    if uid:
        return uid
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer ") and (uid := token_user(bearer[7:].strip())):
        return uid
    if is_local(request):
        return 1
    return None


def authed(request: Request) -> bool:
    return request_user(request) is not None


def _throttled(request: Request) -> tuple[str, list[float], str | None]:
    ip = client_ip(request)
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 600]
    return ip, recent, (too_many_attempts() if len(recent) >= 10 else None)


def _fail(ip: str, recent: list[float]) -> None:
    _fails[ip] = recent + [time.time()]
    time.sleep(1)


def login(request: Request, username: str, password: str):
    """Returns (user, error). 10 failures per IP in 10 minutes -> locked for the rest of the window.
    An empty username means the admin (old PIN/password-only screen)."""
    ip, recent, err = _throttled(request)
    if err:
        return None, err
    user = find_user(username or ADMIN_USERNAME)
    if not user or not user.password_hash or not verify_password(password.strip(), user.password_hash):
        _fail(ip, recent)
        return None, _("Wrong username or password")
    _fails.pop(ip, None)
    return user, None


def check_invite(request: Request, code: str):
    """Same throttle as logins: invite codes must not be brute-forceable."""
    from .db import Invite
    ip, recent, err = _throttled(request)
    if err:
        return None, err
    with _db() as s:
        inv = s.get(Invite, code.strip())
        if not inv or inv.used_by or inv.expires_at < time.strftime("%Y-%m-%dT%H:%M:%S"):
            _fail(ip, recent)
            return None, _("Invalid or expired invitation")
        return inv, None
