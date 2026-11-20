"""قياس النص لاحتواء اليومية في صفحة واحدة لازم يلاقي الخطوط على ويندوز كمان؛ من غير كده القياس
بيرجع لتقدير متشائم وتفشل يومية الضباط بـPageFitError (حصل على جهاز التشغيل)."""
from pathlib import Path

from backend.export_fit import TextMeter

WINDOWS_FONTS = [
    "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf",
]


def test_windows_short_font_file_names_are_matched_and_bold_is_preferred_for_bold():
    meter = TextMeter()
    pick = meter._select_font_path
    assert pick("times new roman", False, WINDOWS_FONTS).endswith("times.ttf")
    assert pick("times new roman", True, WINDOWS_FONTS).endswith("timesbd.ttf")
    assert pick("arial", False, WINDOWS_FONTS).endswith("arial.ttf")      # مش ariblk/Arial Black
    assert pick("arial", True, WINDOWS_FONTS).endswith("arialbd.ttf")


def test_font_roots_include_the_windows_fonts_folder(monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/x/AppData/Local")
    roots = [str(Path(p)).replace("\\", "/") for p in TextMeter._font_roots()]
    assert "C:/Windows/Fonts" in roots
    assert any(r.endswith("Microsoft/Windows/Fonts") for r in roots)
