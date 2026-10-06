#!/usr/bin/env python3
"""Isolated Web Push proof of concept; it never imports production app data."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import threading
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import Flask, abort, jsonify, make_response, render_template, request, send_from_directory
from pywebpush import WebPushException, webpush


ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("WEB_PUSH_DEMO_STATE", "/tmp/personnel-web-push-demo"))
KEY_FILE = STATE_DIR / "vapid-private.pem"
SUBSCRIPTIONS_FILE = STATE_DIR / "subscriptions.json"
TOKEN_FILE = STATE_DIR / "access-token"
LOCK = threading.RLock()

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _access_token() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        _atomic_write(TOKEN_FILE, secrets.token_urlsafe(24))
        TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def _private_key() -> ec.EllipticCurvePrivateKey:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        return serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    KEY_FILE.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    KEY_FILE.chmod(0o600)
    return key


def _public_key() -> str:
    raw = _private_key().public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _subscriptions() -> dict[str, dict]:
    if not SUBSCRIPTIONS_FILE.exists():
        return {}
    try:
        value = json.loads(SUBSCRIPTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_subscriptions(value: dict[str, dict]) -> None:
    _atomic_write(SUBSCRIPTIONS_FILE, json.dumps(value, ensure_ascii=False, indent=2))
    SUBSCRIPTIONS_FILE.chmod(0o600)


def _authorized() -> bool:
    supplied = request.cookies.get("web_push_demo_token", "")
    return secrets.compare_digest(supplied, _access_token())


@app.after_request
def secure_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/")
def index():
    supplied = request.args.get("token", "")
    if supplied and secrets.compare_digest(supplied, _access_token()):
        response = make_response(render_template("index.html"))
        response.set_cookie(
            "web_push_demo_token", supplied, secure=True, httponly=True,
            samesite="Strict", max_age=24 * 60 * 60,
        )
        return response
    if not _authorized():
        abort(404)
    return render_template("index.html")


@app.get("/api/public-key")
def public_key():
    if not _authorized():
        abort(404)
    return jsonify({"public_key": _public_key()})


@app.post("/api/subscribe")
def subscribe():
    if not _authorized():
        abort(404)
    subscription = request.get_json(silent=True) or {}
    endpoint = str(subscription.get("endpoint") or "")
    keys = subscription.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({"error": "invalid subscription"}), 400
    identifier = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:16]
    with LOCK:
        items = _subscriptions()
        items[identifier] = subscription
        _save_subscriptions(items)
    return jsonify({"ok": True, "subscription_id": identifier, "total": len(items)})


@app.get("/api/status")
def status():
    if not _authorized():
        abort(404)
    return jsonify({"subscriptions": len(_subscriptions()), "secure": request.is_secure})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/sw.js")
def service_worker():
    response = make_response(send_from_directory(ROOT / "static", "sw.js"))
    response.headers["Service-Worker-Allowed"] = "/"
    return response


def send_notification(title: str, body: str) -> tuple[int, list[dict]]:
    payload = json.dumps({
        "title": title,
        "body": body,
        "tag": "personnel-web-push-demo",
        "url": "/",
    }, ensure_ascii=False)
    items = _subscriptions()
    outcomes = []
    stale = []
    for identifier, subscription in items.items():
        try:
            response = webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=str(KEY_FILE),
                vapid_claims={"sub": "mailto:web-push-demo@example.invalid"},
                ttl=300,
            )
            outcomes.append({"id": identifier, "status": response.status_code})
        except WebPushException as exc:
            status_code = getattr(exc.response, "status_code", None)
            outcomes.append({"id": identifier, "status": status_code or "error", "error": str(exc)})
            if status_code in {404, 410}:
                stale.append(identifier)
    if stale:
        with LOCK:
            latest = _subscriptions()
            for identifier in stale:
                latest.pop(identifier, None)
            _save_subscriptions(latest)
    return len(items), outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=5091)
    send = sub.add_parser("send")
    send.add_argument("--title", default="اختبار إشعارات اليومية")
    send.add_argument("--body", default="وصل الإشعار بنجاح إلى هاتفك الشخصي.")
    sub.add_parser("status")
    args = parser.parse_args()

    _private_key()
    if args.command == "serve":
        print(f"ACCESS_TOKEN={_access_token()}", flush=True)
        app.run(host="127.0.0.1", port=args.port, debug=False)
        return 0
    if args.command == "status":
        print(json.dumps({"subscriptions": len(_subscriptions())}, ensure_ascii=False))
        return 0
    count, outcomes = send_notification(args.title, args.body)
    print(json.dumps({"attempted": count, "outcomes": outcomes}, ensure_ascii=False, indent=2))
    return 0 if count and all(item["status"] in {200, 201, 202} for item in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
