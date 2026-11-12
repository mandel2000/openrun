import json

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from app import offsite


def test_encrypt_roundtrip_and_wrong_passphrase():
    blob = offsite.encrypt(b"SQLite format 3\x00" + b"x" * 5000, "una frase larga")
    assert blob[:4] == offsite.MAGIC and len(blob) < 1000  # gzipped
    assert offsite.decrypt(blob, "una frase larga").startswith(b"SQLite format 3")
    with pytest.raises(InvalidTag):
        offsite.decrypt(blob, "otra frase")


def test_upload_and_prune(monkeypatch, tmp_path):
    for k, v in {"OPENRUN_BACKUP_B2_KEY_ID": "id", "OPENRUN_BACKUP_B2_KEY": "k", "OPENRUN_BACKUP_B2_BUCKET": "bk",
                 "OPENRUN_BACKUP_PASSPHRASE": "pw", "OPENRUN_BACKUP_B2_KEEP": "2"}.items():
        monkeypatch.setenv(k, v)
    store: dict[str, bytes] = {"openrun/openrun-2026-01-01.db.gz.enc": b"", "openrun/openrun-2026-01-02.db.gz.enc": b""}
    deleted = []

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p.endswith("b2_authorize_account"):
            return httpx.Response(200, json={"accountId": "a", "authorizationToken": "t", "apiInfo": {"storageApi": {
                "apiUrl": "https://api.b2", "downloadUrl": "https://dl.b2", "allowed": {"buckets": [{"id": "B", "name": "bk"}]}}}})
        if p.endswith("b2_get_upload_url"):
            return httpx.Response(200, json={"uploadUrl": "https://up.b2/x", "authorizationToken": "u"})
        if req.url.host == "up.b2":
            store[req.headers["X-Bz-File-Name"]] = req.content
            return httpx.Response(200, json={"fileId": "f"})
        if p.endswith("b2_list_file_names"):
            return httpx.Response(200, json={"files": [{"fileName": n, "fileId": n} for n in store], "nextFileName": None})
        if p.endswith("b2_delete_file_version"):
            name = json.loads(req.content)["fileName"]
            deleted.append(name)
            store.pop(name)
            return httpx.Response(200, json={})
        if req.url.host == "dl.b2":
            return httpx.Response(200, content=store[p.split("/bk/")[1]])
        return httpx.Response(404)

    real = httpx.Client
    monkeypatch.setattr(offsite.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    db = tmp_path / "openrun-2026-01-03.db"
    db.write_bytes(b"data" * 100)
    res = offsite.upload_backup(db)
    assert res["file"] == "openrun/openrun-2026-01-03.db.gz.enc" and deleted == ["openrun/openrun-2026-01-01.db.gz.enc"]
    out = tmp_path / "r.db"
    assert offsite._cli(["download", "latest", str(out)]) == 0 and out.read_bytes() == b"data" * 100
