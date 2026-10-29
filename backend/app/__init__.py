import os as _os

# `.env` files (docker compose env_file, run.sh) often leave variables empty: treat them as unset
# so every os.getenv(..., default) keeps its default.
for _k in [k for k, v in _os.environ.items() if v == "" and (k.startswith("OPENRUN_") or k.endswith("_API_KEY"))]:
    del _os.environ[_k]
