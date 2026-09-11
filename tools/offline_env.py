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
import shutil
import site
import sys
import sysconfig
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / "wheels"

# الحزم اللي لازم تكون موجودة عشان السيستم يشتغل. waitress اختيارية —
# بتخلي التشغيل أثبت، وسيرفر Flask العادي شغّال من غيرها.
REQUIRED = ["flask", "werkzeug", "jinja2", "markupsafe", "itsdangerous", "click"]
OPTIONAL = ["waitress", "blinker", "colorama"]


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

    بتشيل التعليق من `import site` وبتضيف سطر `Lib\\site-packages` لو ناقص،
    وإلا الحزم المفكوكة مش هتتشاف أصلًا. بيرجّع True لو غيّر حاجة.
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

    touched = _enable_site_packages()
    if touched and not quiet:
        print("[*] اتفعّل site-packages في نسخة بايثون المحمولة.")

    target = Path(target) if target else default_target()
    target.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"[*] بيفكّ {len(wheels)} حزمة في:\n    {target}\n")

    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            bad = zf.testzip()
            if bad is not None:
                print(f"[X] الحزمة {wheel.name} تالفة (عند {bad}).")
                return 1
            for member in zf.namelist():
                # مجلد .data بيحتوي سكربتات تشغيل مالهاش لزمة هنا
                if ".data/" in member and "/purelib/" not in member:
                    continue
                zf.extract(member, target)
        if not quiet:
            print(f"    + {wheel.name}")

    if not quiet:
        print()
    return verify(quiet=quiet)


def _missing(names):
    import importlib.util
    return [n for n in names if importlib.util.find_spec(n) is None]


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
    page = client.get("/leaves")
    api = client.get("/api/bootstrap/leaves")
    if page.status_code != 200 or api.status_code != 200:
        print(f"[X] السيستم مابيردّش صح (صفحة {page.status_code}، API {api.status_code}).")
        return 1

    if not quiet:
        import importlib.metadata as _md
        data = api.get_json()
        print(f"[OK] بايثون    : {sys.version.split()[0]}  ({sys.executable})")
        print(f"[OK] Flask     : {_md.version('flask')}")
        opt = [n for n in OPTIONAL if n not in _missing(OPTIONAL)]
        print(f"[OK] اختيارية  : {'، '.join(opt) if opt else 'مفيش'}")
        print(f"[OK] البيانات  : {len(data.get('leaves', []))} راحة، "
              f"{data.get('counts', {}).get('officers', 0)} ضابط على القوة")
        print(f"[OK] الصفحات   : بتفتح وبترد 200")
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
    args = ap.parse_args(argv)

    if args.cmd == "install":
        return install(args.target, args.quiet)
    return verify(args.strict, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
