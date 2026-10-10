#!/usr/bin/env python3
"""إنشاء مدير من سطر الأوامر من غير تشغيل خادم الويب."""
import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.auth import users  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="إنشاء حساب مدير")
    parser.add_argument("--username")
    parser.add_argument("--display-name")
    parser.add_argument("--password-env")
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    username = args.username or input("اسم المستخدم: ").strip()
    display_name = args.display_name or input("الاسم الظاهر: ").strip()
    password = os.environ.get(args.password_env, "") if args.password_env else getpass.getpass("كلمة المرور: ")
    existing = users.by_username(username)
    try:
        if existing:
            if not args.reset_password:
                print("اسم المستخدم موجود بالفعل. استخدم --reset-password لإعادة تعيين كلمته.", file=sys.stderr)
                return 2
            users.change_password(existing["id"], password)
            print("تمت إعادة تعيين كلمة المرور.")
        else:
            users.create(username, display_name, "admin", password, "أداة create_admin")
            print("تم إنشاء حساب المدير.")
    except users.UserError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
