"""ستة أيام من أغسطس 2026 كانت بتفشل بـPageFitError (23-29 خدمة في صفحة
واحدة). بيتخطّى لو بيانات الأيام أو الأرشيف مش موجودين (بيئة CI)."""
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
@pytest.mark.parametrize("day", FAILING_DAYS)
def test_regularity_real_day_fits_one_page(day):
    from backend.day_exports import build_regularity_bytes

    assert build_regularity_bytes(day)
    assert LAST_FIT["page_count"] == 1
    assert 7 <= LAST_FIT["size_pt"] <= 12
