"""يطبع عنوان الموبايل (https://<الجهاز>.<الشبكة>.ts.net) من `tailscale status --json`.

بيستخدمه SETUP_PHONE_ACCESS.bat — الاستخدام: python tools/phone_url.py [مسار tailscale]
"""
import json
import subprocess
import sys


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else "tailscale"
    out = subprocess.run([exe, "status", "--json"], capture_output=True, check=True).stdout
    name = (json.loads(out).get("Self") or {}).get("DNSName", "").rstrip(".")
    if not name:
        return 1
    print(f"https://{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
