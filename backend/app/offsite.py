"""Encrypted off-site copies of the daily database backup (Backblaze B2, native API).

The local backup (services.backup_db) lives on the same disk as the database: it protects
against mistakes, not against losing the server. When configured, each daily snapshot is also
gzipped, encrypted with AES-256-GCM (key derived with scrypt from OPENRUN_BACKUP_PASSPHRASE)
and uploaded to a B2 bucket; the last OPENRUN_BACKUP_B2_KEEP copies are kept.

Environment:
    OPENRUN_BACKUP_B2_KEY_ID, OPENRUN_BACKUP_B2_KEY   application key (restricted to the bucket)
    OPENRUN_BACKUP_B2_BUCKET                          bucket name
    OPENRUN_BACKUP_PASSPHRASE                         encryption passphrase (keep a copy elsewhere!)
    OPENRUN_BACKUP_B2_KEEP                            copies to keep (default 30)

Restore (inside the container or anywhere with the same env vars):
    python -m app.offsite list
    python -m app.offsite download latest restored.db      # or a file name from `list`
    python -m app.offsite decrypt some-file.db.gz.enc restored.db
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import sys
from pathlib import Path

import httpx

log = logging.getLogger("openrun.offsite")

MAGIC = b"ORB1"
PREFIX = "openrun/"
AUTH_URL = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def enabled() -> bool:
    return all(_env(k) for k in ("OPENRUN_BACKUP_B2_KEY_ID", "OPENRUN_BACKUP_B2_KEY", "OPENRUN_BACKUP_B2_BUCKET",
                                  "OPENRUN_BACKUP_PASSPHRASE"))


def keep() -> int:
    try:
        return max(1, int(_env("OPENRUN_BACKUP_B2_KEEP") or 30))
    except ValueError:
        return 30


# ---------------------------------------------------------------- encryption


def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=2**26, dklen=32)


def encrypt(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, gzip.compress(data, 6), MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if blob[:4] != MAGIC:
        raise ValueError("not an OpenRun encrypted backup")
    salt, nonce, ct = blob[4:20], blob[20:32], blob[32:]
    return gzip.decompress(AESGCM(_key(passphrase, salt)).decrypt(nonce, ct, MAGIC))


# ---------------------------------------------------------------- B2 native API


class B2:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=120)
        r = self.http.get(AUTH_URL, auth=(_env("OPENRUN_BACKUP_B2_KEY_ID"), _env("OPENRUN_BACKUP_B2_KEY")))
        r.raise_for_status()
        a = r.json()
        self.account = a["accountId"]
        self.token = a["authorizationToken"]
        api = a["apiInfo"]["storageApi"]
        self.api, self.download_url = api["apiUrl"], api["downloadUrl"]
        name = _env("OPENRUN_BACKUP_B2_BUCKET")
        allowed = [b for b in (api.get("allowed") or {}).get("buckets") or [] if b.get("name") == name]
        self.bucket_id = allowed[0]["id"] if allowed else self._bucket_id(name)

    def _call(self, op: str, body: dict) -> dict:
        r = self.http.post(f"{self.api}/b2api/v3/{op}", json=body, headers={"Authorization": self.token})
        if r.status_code >= 400:
            raise RuntimeError(f"B2 {op}: {r.status_code} {r.text[:200]}")
        return r.json()

    def _bucket_id(self, name: str) -> str:
        buckets = self._call("b2_list_buckets", {"accountId": self.account, "bucketName": name}).get("buckets") or []
        if not buckets:
            raise RuntimeError(f"B2 bucket not found: {name}")
        return buckets[0]["bucketId"]

    def upload(self, name: str, data: bytes) -> dict:
        up = self._call("b2_get_upload_url", {"bucketId": self.bucket_id})
        r = self.http.post(up["uploadUrl"], content=data, headers={
            "Authorization": up["authorizationToken"], "X-Bz-File-Name": name, "Content-Type": "application/octet-stream",
            "X-Bz-Content-Sha1": hashlib.sha1(data).hexdigest()})  # noqa: S324 - B2 integrity check, not security
        if r.status_code >= 400:
            raise RuntimeError(f"B2 upload: {r.status_code} {r.text[:200]}")
        return r.json()

    def files(self) -> list[dict]:
        out, start = [], None
        while True:
            body = {"bucketId": self.bucket_id, "prefix": PREFIX, "maxFileCount": 1000}
            if start:
                body["startFileName"] = start
            res = self._call("b2_list_file_names", body)
            out += res.get("files") or []
            start = res.get("nextFileName")
            if not start:
                return sorted(out, key=lambda f: f["fileName"])

    def delete(self, f: dict) -> None:
        self._call("b2_delete_file_version", {"fileName": f["fileName"], "fileId": f["fileId"]})

    def download(self, name: str) -> bytes:
        bucket = _env("OPENRUN_BACKUP_B2_BUCKET")
        r = self.http.get(f"{self.download_url}/file/{bucket}/{name}", headers={"Authorization": self.token})
        r.raise_for_status()
        return r.content


# ---------------------------------------------------------------- jobs


def upload_backup(path: Path) -> dict | None:
    """Encrypt and upload one local backup file, then prune old copies. None when not configured."""
    if not enabled():
        return None
    blob = encrypt(path.read_bytes(), _env("OPENRUN_BACKUP_PASSPHRASE"))
    b2 = B2()
    name = f"{PREFIX}{path.name}.gz.enc"
    b2.upload(name, blob)
    old = [f for f in b2.files() if f["fileName"].endswith(".enc")][:-keep()]
    for f in old:
        b2.delete(f)
    log.info("off-site backup uploaded: %s (%d KB), pruned %d", name, len(blob) // 1024, len(old))
    return {"file": name, "size": len(blob), "pruned": len(old)}


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] not in ("list", "download", "decrypt"):
        print(__doc__)
        return 2
    pw = _env("OPENRUN_BACKUP_PASSPHRASE")
    if argv[0] == "decrypt":
        Path(argv[2]).write_bytes(decrypt(Path(argv[1]).read_bytes(), pw))
        print(f"restored -> {argv[2]}")
        return 0
    b2 = B2()
    files = b2.files()
    if argv[0] == "list":
        for f in files:
            print(f"{f['fileName']}\t{f.get('contentLength', 0) // 1024} KB")
        return 0
    name = files[-1]["fileName"] if argv[1] == "latest" else argv[1]
    Path(argv[2]).write_bytes(decrypt(b2.download(name), pw))
    print(f"{name} -> {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
