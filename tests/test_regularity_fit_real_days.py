"""ستة أيام من أغسطس 2026 كانت بتفشل بـPageFitError (23-29 خدمة في صفحة
واحدة). بنطبق 022+023 في الذاكرة الأول، عشان 22/8 يتقاس بملاحظات الانتظام
الطويلة اللي استوردتها 023، مش البيانات الأقدم. بيتخطّى لو البيانات/الأرشيف مش موجودين."""
from copy import deepcopy
from pathlib import Path

import pytest

from backend import store
from backend.regularity_export import LAST_FIT

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT.parent.parent / "2026"
FAILING_DAYS = ("2026-08-06", "2026-08-12", "2026-08-14",
                "2026-08-15", "2026-08-22", "2026-08-26")


def _have_real_data():
    days = Path(store.DATA_DIR) / "days" / "2026" / "08"
    return ARCHIVE.is_dir() and all((days / f"{day}.json").exists() for day in FAILING_DAYS)


@pytest.mark.skipif(not _have_real_data(), reason="بيانات الأيام أو الأرشيف غير موجودة")
def test_regularity_real_days_fit_one_page_after_022_and_023(tmp_path, monkeypatch):
    from backend.day_exports import build_regularity_bytes
    from importer import archive_gaps, campaign

    # مفيش كتابة على data/ الحقيقي: الهجرتين على نسخة مجمعة، وبعدها
    # core.json + days/ بس في مجلد pytest المؤقت.
    data = deepcopy(store.assemble())
    # نحوّل المسار قبل أي مرحلة استيراد؛ بعض الـhooks/الـrepos بتقرأ
    # store.DATA_DIR مباشرة حتى لو العملية نفسها على dict في الذاكرة.
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    store._cache.clear()
    campaign.run_import(data, ARCHIVE, "2026-08-01", "2026-10-22", apply=True)
    archive_gaps.run_import(data, ARCHIVE, "2026-08-01", "2026-10-22", apply=True)
    store.explode(data, _notify=False)

    for day in FAILING_DAYS:
        assert build_regularity_bytes(day)
        assert LAST_FIT["page_count"] == 1
        assert 7 <= LAST_FIT["size_pt"] <= 12
