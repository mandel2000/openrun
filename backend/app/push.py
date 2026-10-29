"""Web Push notifications (no third-party app: the browser / installed PWA receives them).

VAPID keys are generated on first use and kept in <data>/vapid.pem. iPhone needs iOS 16.4+ and the
app added to the Home Screen; Android/desktop Chrome, Edge and Firefox work in the browser.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
from pathlib import Path

from sqlmodel import Session, select

from .db import PushSubscription, engine
from .i18n import _

log = logging.getLogger("openrun.push")
DATA = Path(os.getenv("OPENRUN_DATA", str(Path.home() / ".openrun")))
KEY_FILE = DATA / "vapid.pem"
SUB = os.getenv("OPENRUN_VAPID_SUB", "mailto:openrun@users.noreply.github.com")


def _vapid():
    from py_vapid import Vapid01

    if not KEY_FILE.exists():
        v = Vapid01()
        v.generate_keys()
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        v.save_key(str(KEY_FILE))
        KEY_FILE.chmod(0o600)
    return Vapid01.from_file(str(KEY_FILE))


def public_key() -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw = _vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# Browsers' push services. The server POSTs to the subscription endpoint, so only these hosts are
# accepted (otherwise a user could make the server call arbitrary URLs).
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", ".push.apple.com", ".notify.windows.com",
              "android.googleapis.com")


def _allowed(endpoint: str) -> bool:
    from urllib.parse import urlparse

    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h.lstrip(".") or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS)


def subscribe(uid: int, sub: dict) -> None:
    endpoint = sub.get("endpoint", "")
    keys = sub.get("keys") or {}
    if not _allowed(endpoint) or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError(_("Invalid subscription"))
    with Session(engine) as s:
        row = s.exec(select(PushSubscription).where(PushSubscription.endpoint == endpoint)).first()
        row = row or PushSubscription(endpoint=endpoint, user_id=uid)
        row.user_id, row.keys = uid, {"p256dh": keys["p256dh"], "auth": keys["auth"]}
        row.created_at = row.created_at or dt.datetime.now().isoformat(timespec="seconds")
        s.add(row)
        s.commit()


def unsubscribe(uid: int, endpoint: str) -> None:
    with Session(engine) as s:
        row = s.exec(select(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == uid)).first()
        if row:
            s.delete(row)
            s.commit()


def count(uid: int) -> int:
    with Session(engine) as s:
        return len(s.exec(select(PushSubscription).where(PushSubscription.user_id == uid)).all())


def send(uid: int, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Send to every device of the user; drops subscriptions the push service says are gone."""
    from pywebpush import WebPushException, webpush

    with Session(engine) as s:
        subs = s.exec(select(PushSubscription).where(PushSubscription.user_id == uid)).all()
        if not subs:
            return 0
        vapid = _vapid()
        payload = json.dumps({"title": title, "body": body[:300], "url": url, "tag": tag}, ensure_ascii=False)
        sent = 0
        for sub in subs:
            try:
                webpush({"endpoint": sub.endpoint, "keys": sub.keys}, payload, vapid_private_key=vapid,
                        vapid_claims={"sub": SUB}, ttl=6 * 3600, timeout=10)
                sent += 1
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):
                    s.delete(sub)
                else:
                    log.warning("push failed (%s): %s", status, e)
            except Exception:  # noqa: BLE001 - one device failing must not stop the rest
                log.warning("push failed", exc_info=True)
        s.commit()
        return sent
