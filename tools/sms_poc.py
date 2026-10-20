"""تجربة إرسال SMS (إثبات فكرة) — من غير أي خدمة مدفوعة ومن غير نت.

الفكرة: موبايل أندرويد عليه شريحة + تطبيق "SMS Gateway for Android"
(https://github.com/capcom6/android-sms-gateway) في وضع Local Server.
السيستم بيكلّم الموبايل على نفس شبكة الواي فاي، والموبايل بيبعت الرسالة من الشريحة
بتاعته — يعني التكلفة الوحيدة هي رصيد/باقة رسائل الشريحة.

تجهيز الموبايل:
  1. نزّل التطبيق (APK من صفحة Releases على GitHub أو من Google Play).
  2. فعّل "Local Server" واضغط "Offline" — هيظهر IP الموبايل واسم المستخدم وكلمة السر.
  3. خلّي الموبايل والكمبيوتر على نفس الشبكة.

التشغيل:
  python tools/sms_poc.py --host 192.168.1.50 --user sms --password XXXX ^
      --to 01012345678 --text "تجربة من سيستم المعسكر"

  أو حط الإعدادات في متغيرات بيئة: SMS_GATEWAY_HOST / SMS_GATEWAY_USER / SMS_GATEWAY_PASSWORD
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = 8080


def normalize_eg_number(number):
    """01012345678 → +201012345678 ؛ الأرقام اللي فيها كود دولة بتعدّي زي ما هي."""
    digits = "".join(ch for ch in number if ch.isdigit() or ch == "+")
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0"):
        return "+20" + digits[1:]
    if digits.startswith("20"):
        return "+" + digits
    return digits


def _request(method, url, user, password, body=None):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def send_sms(base_url, user, password, numbers, text):
    body = {"textMessage": {"text": text}, "phoneNumbers": numbers}
    return _request("POST", f"{base_url}/message", user, password, body)


def get_status(base_url, user, password, message_id):
    return _request("GET", f"{base_url}/message/{message_id}", user, password)


def main():
    p = argparse.ArgumentParser(description="تجربة إرسال SMS عن طريق موبايل أندرويد")
    p.add_argument("--host", default=os.environ.get("SMS_GATEWAY_HOST"), help="IP الموبايل")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=os.environ.get("SMS_GATEWAY_USER"))
    p.add_argument("--password", default=os.environ.get("SMS_GATEWAY_PASSWORD"))
    p.add_argument("--to", required=True, nargs="+", help="رقم أو أكتر")
    p.add_argument("--text", required=True)
    args = p.parse_args()

    if not (args.host and args.user and args.password):
        p.error("لازم --host و --user و --password (أو متغيرات البيئة)")

    base_url = f"http://{args.host}:{args.port}"
    numbers = [normalize_eg_number(n) for n in args.to]
    print(f"بيبعت لـ {', '.join(numbers)} عن طريق {base_url} ...")

    try:
        result = send_sms(base_url, args.user, args.password, numbers, args.text)
    except urllib.error.HTTPError as e:
        print(f"الموبايل رفض الطلب ({e.code}): {e.read().decode('utf-8', 'replace')}")
        if e.code == 401:
            print("← اسم المستخدم أو كلمة السر غلط.")
        return 1
    except urllib.error.URLError as e:
        print(f"مش قادر يوصل للموبايل: {e.reason}")
        print("← اتأكد إن Local Server شغّال وإن الجهازين على نفس الشبكة.")
        return 1

    message_id = result.get("id")
    print(f"اتقبلت الرسالة — id={message_id} state={result.get('state')}")

    # متابعة الحالة لحد ما تتبعت أو تفشل (حوالي 30 ثانية بالكتير)
    for _ in range(10):
        if not message_id:
            break
        time.sleep(3)
        try:
            status = get_status(base_url, args.user, args.password, message_id)
        except urllib.error.URLError:
            break
        state = status.get("state")
        print(f"  الحالة: {state}")
        for r in status.get("recipients", []):
            if r.get("error"):
                print(f"  {r.get('phoneNumber')}: {r.get('error')}")
        if state in ("Sent", "Delivered", "Failed"):
            return 0 if state != "Failed" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
