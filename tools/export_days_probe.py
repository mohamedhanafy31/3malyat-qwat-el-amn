#!/usr/bin/env python3
"""Export the daily .docx files from the SYSTEM for a range of days, for fidelity
checks against the archive. Read-only: uses Flask's test client with an in-process
session, so run it with PERSONNEL_DATA_DIR pointing at a COPY of data/ (never live).

    PERSONNEL_DATA_DIR=/abs/copy python3 tools/export_days_probe.py --out /abs/out 2026-09-28 [2026-09-29 ...]
Writes <out>/<YYYY-MM-DD>/{board,duty,afraad,campaign}.docx (+ status lines).
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KINDS = {"board": "/api/board/{d}/export.docx", "duty": "/api/duty/{d}/export.docx",
         "afraad": "/api/afraad/{d}/export.docx", "campaign": "/api/campaign/{d}/export.docx"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("days", nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("PERSONNEL_DATA_DIR"):
        print("refusing to run on the live data dir: set PERSONNEL_DATA_DIR to a copy", file=sys.stderr)
        return 2
    from app import app
    from backend.auth.users import by_username
    user = by_username("testadmin")
    if not user:
        print("create the test admin first (tools/create_admin.py --username testadmin ...)", file=sys.stderr)
        return 2
    app.config.update(TESTING=True)
    from backend.auth.security import secret_key
    app.secret_key = secret_key()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["session_version"] = int(user.get("session_version", 0))
        sess.permanent = True
    for day in args.days:
        for kind, url in KINDS.items():
            response = client.get(url.format(d=day))
            target = args.out / day / f"{kind}.docx"
            target.parent.mkdir(parents=True, exist_ok=True)
            if response.status_code == 200:
                target.write_bytes(response.data)
            print(day, kind, response.status_code, len(response.data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
