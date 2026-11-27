import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "headers.db"))
os.environ["OPENRUN_SCHEDULER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


def test_referrer_policy_sends_origin_to_map_tiles():
    """OpenStreetMap rejects tile requests without a Referer (the map shows "Access blocked"),
    so the cross-origin referrer policy must not strip it."""
    c = TestClient(main.app, client=("203.0.113.5", 5000))
    r = c.get("/api/health")
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
