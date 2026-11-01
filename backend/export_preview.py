"""معاينة ملفات التصدير قبل التحميل: الملف ← PDF ← صور PNG لكل صفحة.

المحرك:
- «word»: على جهاز التشغيل (ويندوز وعليه Office) Word/Excel نفسهم بيعملوا الـPDF،
  فالمعاينة مطابقة للي هيتطبع بالظبط.
- «libreoffice»: للتطوير على لينكس؛ تقريبية (خطوط ومحرك تخطيط مختلفين).
EXPORT_PREVIEW_ENGINE = auto (الافتراضي) | word | libreoffice.

العرض صور جاهزة من السيرفر عشان خطوط المتصفح ماتبوّظش العربي، ولو المستخدم وافق
بيتحمّل نفس الملف اللي اتعاين بالظبط.
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path

MAX_BYTES = 15 * 1024 * 1024
TIMEOUT_SECONDS = 90
KINDS = {"docx", "xlsx"}
_LOCK = threading.Lock()  # بروفايل LibreOffice الواحد مايتفتحش من عمليتين مع بعض


class PreviewUnavailable(RuntimeError):
    """المعاينة مش متاحة على الجهاز ده؛ التحميل المباشر لسه شغال."""


def _binary():
    return shutil.which("soffice") or shutil.which("libreoffice")


def _work_root(binary):
    """فولدر الشغل. LibreOffice المتثبّت كـ snap مابيشوفش /tmp بتاع الجهاز ولا
    الفولدرات المخفية، فبنشتغل في فولدر ظاهر جوه home."""
    configured = os.environ.get("EXPORT_PREVIEW_DIR")
    if configured:
        root = Path(configured)
    elif "/snap/" in str(Path(binary).resolve()) or str(binary).startswith("/snap/"):
        root = Path.home() / "personnel-export-preview"
    else:
        root = Path(tempfile.gettempdir()) / "personnel-export-preview"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _for_libreoffice(content):
    """نسخة للمعاينة بس: الجداول العايمة (tblpPr) — زي جدول خط تشكيل ليل من قالب
    الأرشيف — LibreOffice بيزقّها لصفحة جديدة فالمعاينة كانت بتطلع 3 صفحات. بنخليها
    جداول عادية في مكانها؛ الملف اللي بيتحمّل نفسه ما بيتغيرش."""
    source = zipfile.ZipFile(io.BytesIO(content))
    xml = source.read("word/document.xml").decode("utf-8")
    fixed = re.sub(r"<w:tblpPr\b[^>]*/>", "", xml)
    if fixed == xml:
        return content
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = fixed.encode("utf-8") if item.filename == "word/document.xml" else source.read(item.filename)
            target.writestr(item, data)
    return output.getvalue()


_IGNORED_FONTS = {"Calibri", "Calibri Light", "Cambria"}  # خطوط الثيم الافتراضية؛ مش مستخدمة في نص الملفات


def _installed_fonts():
    try:
        output = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {name.strip().casefold() for line in output.splitlines() for name in line.split(",")}


def missing_fonts(content, kind):
    """الخطوط اللي الملف بيطلبها ومش متثبتة هنا — بسببها المعاينة ممكن تختلف عن Word."""
    if kind != "docx":
        return []
    try:
        xml = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml").decode("utf-8")
    except (KeyError, zipfile.BadZipFile):
        return []
    wanted = set(re.findall(r'w:(?:ascii|hAnsi|cs)="([^"]+)"', xml)) - _IGNORED_FONTS
    installed = _installed_fonts()
    if installed is None:
        return []
    return sorted(name for name in wanted if name.casefold() not in installed)


def _office_installed():
    if os.name != "nt":
        return False
    try:
        import win32com.client  # noqa: F401  (pywin32)
    except ImportError:
        return False
    return True


def engines():
    """المحركات المتاحة بالترتيب المفضّل."""
    choice = os.environ.get("EXPORT_PREVIEW_ENGINE", "auto").strip().lower()
    found = []
    if choice in ("auto", "word") and _office_installed():
        found.append("word")
    if choice in ("auto", "libreoffice") and _binary():
        found.append("libreoffice")
    return found


def available():
    return bool(engines())


def _check(content, kind):
    if kind not in KINDS:
        raise ValueError("نوع الملف غير مدعوم في المعاينة.")
    if not content or len(content) > MAX_BYTES or not content.startswith(b"PK"):
        raise ValueError("الملف المرسل للمعاينة غير صالح.")


def _office_to_pdf(content, kind):
    """Word/Excel نفسهم عن طريق COM — نفس محرك الطباعة اللي في المكتب."""
    import pythoncom
    import pywintypes
    import win32com.client

    pythoncom.CoInitialize()
    try:
        with _LOCK, tempfile.TemporaryDirectory(prefix="export-preview-") as tmp:
            source = Path(tmp) / f"preview.{kind}"
            output = Path(tmp) / "preview.pdf"
            source.write_bytes(content)
            if kind == "docx":
                app = win32com.client.DispatchEx("Word.Application")
                app.Visible = False
                app.DisplayAlerts = 0
                try:
                    document = app.Documents.Open(str(source), ConfirmConversions=False, ReadOnly=True,
                                                  AddToRecentFiles=False, Visible=False)
                    document.ExportAsFixedFormat(str(output), 17)  # wdExportFormatPDF
                    document.Close(False)
                finally:
                    app.Quit()
            else:
                app = win32com.client.DispatchEx("Excel.Application")
                app.Visible = False
                app.DisplayAlerts = False
                try:
                    book = app.Workbooks.Open(str(source), ReadOnly=True)
                    book.ExportAsFixedFormat(0, str(output))  # xlTypePDF
                    book.Close(False)
                finally:
                    app.Quit()
            if not output.exists():
                raise PreviewUnavailable("تعذّر تجهيز المعاينة لهذا الملف.")
            return output.read_bytes()
    except pywintypes.com_error as exc:
        raise PreviewUnavailable("تعذّر تشغيل Microsoft Office لتجهيز المعاينة.") from exc
    finally:
        pythoncom.CoUninitialize()


def _libreoffice_to_pdf(content, kind):
    binary = _binary()
    if not binary:
        raise PreviewUnavailable("المعاينة غير متاحة على هذا الجهاز (LibreOffice غير مثبّت).")
    root = _work_root(binary)
    # البروفايل ثابت: أول تشغيل بيبنيه (بطيء) والباقي بيستخدمه.
    profile = root / "profile"
    with _LOCK, tempfile.TemporaryDirectory(prefix="job-", dir=root) as tmp:
        folder = Path(tmp)
        source = folder / f"preview.{kind}"
        try:
            prepared = _for_libreoffice(content) if kind == "docx" else content
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError("الملف المرسل للمعاينة غير صالح.") from exc
        source.write_bytes(prepared)
        command = [binary, f"-env:UserInstallation={profile.as_uri()}", "--headless",
                   "--norestore", "--nologo", "--convert-to", "pdf", "--outdir", str(folder), str(source)]
        try:
            subprocess.run(command, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired as exc:
            raise PreviewUnavailable("تجهيز المعاينة أخذ وقتًا أطول من اللازم.") from exc
        output = folder / "preview.pdf"
        if not output.exists():
            raise PreviewUnavailable("تعذّر تجهيز المعاينة لهذا الملف.")
        return output.read_bytes()


def to_pdf(content, kind):
    """بيرجع (pdf, المحرك). لو Word فشل بنجرّب LibreOffice لو موجود."""
    _check(content, kind)
    found = engines()
    if not found:
        raise PreviewUnavailable("المعاينة غير متاحة على هذا الجهاز (لا Microsoft Office ولا LibreOffice).")
    error = None
    for engine in found:
        try:
            convert = _office_to_pdf if engine == "word" else _libreoffice_to_pdf
            return convert(content, kind), engine
        except PreviewUnavailable as exc:
            error = exc
    raise error


def _rasterize(pdf, dpi):
    try:
        import fitz  # PyMuPDF — على ويندوز مفيش pdftoppm
    except ImportError:
        fitz = None
    if fitz is not None:
        with fitz.open(stream=pdf, filetype="pdf") as document:
            return [page.get_pixmap(dpi=dpi).tobytes("png") for page in document]
    renderer = shutil.which("pdftoppm")
    if not renderer:
        raise PreviewUnavailable("المعاينة غير متاحة على هذا الجهاز (PyMuPDF أو pdftoppm غير مثبّت).")
    with tempfile.TemporaryDirectory(prefix="export-pages-") as tmp:
        folder = Path(tmp)
        (folder / "preview.pdf").write_bytes(pdf)
        try:
            subprocess.run([renderer, "-r", str(dpi), "-png", str(folder / "preview.pdf"), str(folder / "page")],
                           capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired as exc:
            raise PreviewUnavailable("تجهيز المعاينة أخذ وقتًا أطول من اللازم.") from exc
        # pdftoppm بيرقّم page-1 أو page-01 حسب عدد الصفحات؛ الترتيب بالرقم مش بالنص.
        files = sorted(folder.glob("page-*.png"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
        if not files:
            raise PreviewUnavailable("تعذّر تجهيز المعاينة لهذا الملف.")
        return [path.read_bytes() for path in files]


def to_pages(content, kind, dpi=110):
    """بيرجع (صور PNG لصفحات الملف بالترتيب، المحرك)."""
    pdf, engine = to_pdf(content, kind)
    return _rasterize(pdf, dpi), engine
