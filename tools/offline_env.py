#!/usr/bin/env python3
"""تجهيز بيئة التشغيل والتحقق منها — **من غير إنترنت ومن غير pip**.

الحزم اللي السيستم محتاجها (Flask ومعتمداته) بتتنزّل مرة واحدة على جهاز
فيه نت في مجلد `wheels/`، والملف ده بيفكّها في مكانها على الجهاز المعزول.

ليه مش pip؟ نسخة بايثون المحمولة (embeddable) مابتجيش ومعاها pip أصلًا،
وملف الـwheel هو ملف zip عادي — ففكّه بمكتبة zipfile القياسية بيعمل نفس
اللي pip بيعمله للحزم المكتوبة بالبايثون، من غير أي أداة زيادة.

    python tools/offline_env.py install            # فكّ الحزم في بيئة التشغيل
    python tools/offline_env.py install --target D:\\path\\site-packages
    python tools/offline_env.py verify             # اتأكد إن كل حاجة تمام
    python tools/offline_env.py verify --strict    # وكمان امنع أي اتصال شبكة

كل الأوامر دي مالهاش أي اتصال بالشبكة — لا تنزيل ولا فحص تحديثات.
"""
import argparse
import importlib
import os
import shutil
import site
import sys
import sysconfig
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / "wheels"

REQUIRED = ["flask", "werkzeug", "jinja2", "markupsafe", "itsdangerous", "click", "docx",
            "openpyxl", "numpy", "cv2", "PIL", "pytesseract", "waitress"]
OPTIONAL = ["blinker", "colorama"]

# Exit code for "packages are fine but the configured data is not": setup keeps
# the freshly installed packages and reports the data problem on its own.
DATA_INVALID = 3


def default_target():
    """مجلد site-packages بتاع المفسّر الشغّال دلوقتي."""
    for path in site.getsitepackages() if hasattr(site, "getsitepackages") else []:
        if path.endswith("site-packages"):
            return Path(path)
    purelib = sysconfig.get_paths().get("purelib")
    if purelib:
        return Path(purelib)
    return Path(sys.prefix) / "Lib" / "site-packages"


def _enable_site_packages():
    """نسخة بايثون المحمولة بتقفل site-packages افتراضيًا في ملف `._pth`.

    بتشيل التعليق من `import site` وبتضيف جذر المشروع (`..`) و
    `Lib\\site-packages` لو ناقصين. ده ضروري لنسخة Python Embedded لأن
    ملف `._pth` بيعطّل إضافة مجلد السكربت تلقائيًا. بيرجّع True لو غيّر حاجة.
    """
    pth_files = list(Path(sys.prefix).glob("python*._pth"))
    if not pth_files:
        return False                     # مش نسخة محمولة — مفيش حاجة تتعمل
    pth = pth_files[0]
    lines = pth.read_text(encoding="utf-8").splitlines()
    changed = False
    if not any(l.strip() == "import site" for l in lines):
        lines = [("import site" if l.strip() in ("#import site", "# import site") else l)
                 for l in lines]
        if not any(l.strip() == "import site" for l in lines):
            lines.append("import site")
        changed = True
    project_entry = os.path.relpath(ROOT, Path(sys.prefix)).replace("/", "\\")
    if project_entry not in {line.strip().replace("/", "\\") for line in lines}:
        lines.insert(0, project_entry)
        changed = True
    if not any(l.strip().lower().replace("/", "\\") == "lib\\site-packages" for l in lines):
        lines.insert(max(0, len(lines) - 1), r"Lib\site-packages")
        changed = True
    if changed:
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def install(target=None, quiet=False):
    if not WHEELS.is_dir():
        print(f"[X] مافيش مجلد الحزم: {WHEELS}\n"
              f"    شغّل PREPARE_ONLINE.bat على جهاز فيه نت الأول.")
        return 1
    wheels = sorted(WHEELS.glob("*.whl"))
    if not wheels:
        print(f"[X] مجلد {WHEELS.name}/ فاضي — مفيش حزم تتثبّت.")
        return 1

    target = Path(target) if target else default_target()
    staging = target.with_name(target.name + ".staging")
    previous = target.with_name(target.name + ".previous")
    pth_files = list(Path(sys.prefix).glob("python*._pth"))
    pth_backup = (pth_files[0], pth_files[0].read_bytes()) if pth_files else None
    target.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"[*] بيفكّ {len(wheels)} حزمة في:\n    {target}\n")

    # 1) Extract into a staging folder next to the target.  The live
    #    site-packages is untouched until every wheel extracted cleanly.
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir()
        for wheel in wheels:
            problem = _extract_wheel(wheel, staging)
            if problem:
                print(f"[X] {problem}")
                shutil.rmtree(staging, ignore_errors=True)
                return 1
            if not quiet:
                print(f"    + {wheel.name}")
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"[X] فشل فكّ الحزم في مجلد التجهيز {staging}: {exc}")
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    # 2) Activate: keep the old folder as `.previous` until verification passes.
    try:
        if previous.exists():
            shutil.rmtree(previous)
        if target.exists():
            target.rename(previous)
        staging.rename(target)
    except OSError as exc:
        print(f"[X] تعذّر تفعيل الحزم الجديدة في {target}: {exc}")
        print("    اقفل أي نافذة للسيستم (STOP_SYSTEM.bat) وجرّب تاني. البيئة القديمة محفوظة.")
        if previous.exists() and not target.exists():
            previous.rename(target)
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    touched = _enable_site_packages()
    if touched and not quiet:
        print("[*] اتفعّل site-packages في نسخة بايثون المحمولة.")

    # Editing python311._pth only affects the next interpreter process.  The
    # installer verifies in this same process, so activate the freshly
    # extracted packages explicitly instead of reporting them as missing on
    # the first offline setup run.
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    site.addsitedir(str(target))
    importlib.invalidate_caches()

    if not quiet:
        print()
    result = verify(quiet=quiet)
    if result in (0, DATA_INVALID):
        shutil.rmtree(previous, ignore_errors=True)
        return result

    # 3) Verification failed: roll back to the previous packages if there were any.
    if previous.exists():
        failed = target.with_name(target.name + ".failed")
        try:
            if failed.exists():
                shutil.rmtree(failed)
            target.rename(failed)
            previous.rename(target)
            shutil.rmtree(failed, ignore_errors=True)
            print(f"[X] التحقق فشل — اتسترجعت الحزم السابقة في {target}.")
        except OSError as exc:
            print(f"[X] التحقق فشل وتعذّر الاسترجاع التلقائي ({exc}). "
                  f"الحزم السابقة محفوظة في {previous}.")
    elif target.exists():
        shutil.rmtree(target, ignore_errors=True)
        print(f"[X] التحقق فشل — اتمسحت البيئة الجديدة غير الصالحة من {target}.")
    if pth_backup is not None:
        try:
            pth_backup[0].write_bytes(pth_backup[1])
        except OSError as exc:
            print(f"[X] تعذّر استرجاع ملف Python المحمول {pth_backup[0]}: {exc}")
    return result


def _extract_wheel(wheel, destination):
    """Extract one wheel under `destination`; returns an error message or None."""
    base = Path(destination).resolve()
    with zipfile.ZipFile(wheel) as zf:
        bad = zf.testzip()
        if bad is not None:
            return f"الحزمة {wheel.name} تالفة (عند {bad})."
        for member in zf.namelist():
            # مجلد .data بيحتوي سكربتات تشغيل مالهاش لزمة هنا
            if ".data/" in member and "/purelib/" not in member:
                continue
            relative = member
            marker = ".data/purelib/"
            if marker in member:
                relative = member.split(marker, 1)[1]
            if not relative:
                continue
            out = (base / relative).resolve()
            if out != base and base not in out.parents:
                return f"الحزمة {wheel.name} فيها مسار خارج مجلد التثبيت: {member}"
            if member.endswith("/"):
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, out.open("wb") as target:
                    shutil.copyfileobj(source, target)
    return None


def _missing(names):
    import importlib.util
    return [n for n in names if importlib.util.find_spec(n) is None]


def validate_data():
    """Read-only validation of the configured data and every day file.

    -> (info dict, None) on success or (None, printable error) on failure.
    The only write it can cause is the store's normal transaction-journal
    recovery; it never creates default data or migrates anything.
    """
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from backend import store
    from tools import deploy_check
    hint = ("[X] Data folder: {folder}. No data was modified. Restore a good backup with "
            "BACKUPS.bat; for a schema mismatch run the migration scripts in migrations\\ "
            "(they back up first) or update the application.")
    # A running server owns the transaction journal: never replay it from here.
    owned = deploy_check.is_file_locked(store.DATA_DIR / store.LOCK_FILE_NAME)
    try:
        return store.validate_data(full=True, recover=not owned), None
    except store.SchemaMismatch as exc:
        kind = "unreadable or corrupt" if isinstance(exc, store.DataUnreadable) else "schema mismatch"
        return None, (f"[X] Data validation failed ({kind}): {exc}\n"
                      + hint.format(folder=store.DATA_DIR))
    except Exception as exc:                      # unexpected structure: still a clear failure
        return None, (f"[X] Data validation failed ({type(exc).__name__}): {exc}\n"
                      + hint.format(folder=store.DATA_DIR))


def _describe_data(info):
    if info["status"] == "fresh":
        return "مجلد البيانات فاضي — هيتجهّز عند أول استخدام"
    return f"سليمة (بنية {info['schema']}، {info['days']} يوم)"


def check_data(quiet=False):
    info, error = validate_data()
    if error:
        print(error)
        return DATA_INVALID
    if not quiet:
        print(f"[OK] البيانات  : {_describe_data(info)}")
    return 0


def verify(strict=False, quiet=False):
    """يتأكد إن البيئة جاهزة. strict=True كمان بيمنع أي اتصال شبكة ويجرّب."""
    if strict:
        _block_network()

    # وحدات بايثون الأساسية اللي السيستم بيقف عليها فعلًا. الفحص ده مهم مع
    # النسخة المحمولة تحديدًا: لو ملف .pyd ناقص من runtime\ (نسخة ناقصة أو
    # فكّ ضغط مقطوع) الفحص بالـtest client كان هيعدّي بنجاح لأنه مابيفتحش
    # سوكت حقيقي ولا بيضغط ملف — والفشل كان هيظهر بعدين وقت التشغيل بس.
    for mod, why in (("socket", "السيرفر مايقدرش يفتح المنفذ"),
                     ("zlib", "النسخ الاحتياطية المضغوطة مش هتشتغل"),
                     ("gzip", "النسخ الاحتياطية المضغوطة مش هتشتغل")):
        try:
            __import__(mod)
        except ImportError:
            print(f"[X] وحدة «{mod}» ناقصة من بيئة بايثون — {why}.")
            print("    نسخة بايثون في runtime\\ ناقصة أو فكّ الضغط مكملش.")
            print("    امسح مجلد runtime\\ وجهّزه تاني بـPREPARE_ONLINE.bat.")
            return 1
    # ترميز UTF-8 لازم يكون شغّال — كل البيانات عربي
    if "أ".encode("utf-8").decode("utf-8") != "أ":
        print("[X] ترميز UTF-8 مش شغّال صح في بيئة بايثون دي.")
        return 1

    missing = _missing(REQUIRED)
    if missing:
        print("[X] حزم ناقصة: " + "، ".join(missing))
        print("    شغّل SETUP_OFFLINE.bat مرة واحدة على الجهاز ده.")
        return 1

    import flask                                        # noqa: F401
    sys.path.insert(0, str(ROOT))
    from app import app                                 # noqa: E402
    app.config["TESTING"] = True
    client = app.test_client()
    login = client.get("/login")
    setup = client.get("/setup")
    page = client.get("/leaves")
    api = client.get("/api/bootstrap/leaves")
    # A fresh offline package intentionally excludes users and secrets.  The
    # protected page/API must therefore redirect/reject until the first admin
    # is created; treating 302/401 as an installation failure made a secure
    # fresh install impossible.
    entry_ok = login.status_code == 200 or setup.status_code == 200
    if (not entry_ok or page.status_code not in (200, 302)
            or api.status_code not in (200, 401)):
        print(f"[X] السيستم مابيردّش صح (دخول {login.status_code}، إعداد {setup.status_code}، "
              f"صفحة {page.status_code}، API {api.status_code}).")
        return 1

    # The protected endpoints above are intercepted by authentication before
    # any data file is read, so they say nothing about the data.  Load and
    # validate the real configured data directly (read-only).
    info, error = validate_data()
    if error:
        print(error)
        return DATA_INVALID
    health = client.get("/api/health/ready")
    body = health.get_json(silent=True) or {}
    if (health.status_code != 200 or body.get("service") != "personnel-system"
            or body.get("status") != "ready"):
        print(f"[X] Readiness endpoint is not ready (HTTP {health.status_code}).")
        return 1

    if not quiet:
        import importlib.metadata as _md
        print(f"[OK] بايثون    : {sys.version.split()[0]}  ({sys.executable})")
        print(f"[OK] Flask     : {_md.version('flask')}")
        opt = [n for n in OPTIONAL if n not in _missing(OPTIONAL)]
        print(f"[OK] اختيارية  : {'، '.join(opt) if opt else 'مفيش'}")
        print(f"[OK] البيانات  : {_describe_data(info)}")
        print(f"[OK] الصفحات   : صفحة الدخول تعمل والحماية مفعلة")
        print(f"[OK] الأساسيات : socket / zlib / gzip / UTF-8 شغّالين")
        if strict:
            print("[OK] الشبكة    : أي اتصال خارجي كان هيتمنع — ومحصلش أي محاولة")
        print("\nالبيئة جاهزة للتشغيل بدون إنترنت.")
    return 0


def _block_network():
    """يمنع أي اتصال بره الجهاز — أي محاولة بترمي استثناء واضح."""
    import socket
    real_connect = socket.socket.connect

    def guarded(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"محاولة اتصال خارجي مرفوضة: {host}")
        return real_connect(self, address, *a, **kw)

    socket.socket.connect = guarded
    socket.create_connection = lambda addr, *a, **kw: (_ for _ in ()).throw(
        RuntimeError(f"محاولة اتصال خارجي مرفوضة: {addr}"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_i = sub.add_parser("install", help="فكّ الحزم من wheels/ في بيئة التشغيل")
    p_i.add_argument("--target", default=None)
    p_i.add_argument("--quiet", action="store_true")
    p_v = sub.add_parser("verify", help="اتأكد إن البيئة جاهزة")
    p_v.add_argument("--strict", action="store_true", help="امنع أي اتصال شبكة أثناء الفحص")
    p_v.add_argument("--quiet", action="store_true")
    p_d = sub.add_parser("check-data", help="تحقق من ملفات البيانات الفعلية (قراءة فقط)")
    p_d.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "install":
        return install(args.target, args.quiet)
    if args.cmd == "check-data":
        return check_data(args.quiet)
    return verify(args.strict, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
