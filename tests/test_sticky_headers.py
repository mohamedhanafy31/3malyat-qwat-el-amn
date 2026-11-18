"""رؤوس الجداول اللاصقة: أي حاوية overflow:hidden/auto حوالين جدول بتخلّي top:var(--topbar-h) يتحسب منها
فالرأس بيتزحلق لتحت فوق أول صف (باج الخوارج في اليومية التفصيلية)."""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "static" / "css"
COMPONENTS = (CSS / "components.css").read_text(encoding="utf-8")
PAGES = (CSS / "pages.css").read_text(encoding="utf-8")


def _rule(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


def test_containers_around_sticky_tables_clip_instead_of_becoming_scroll_containers():
    for selector in (".outsider-group", ".panel", ".mcard"):
        body = _rule(COMPONENTS, selector)
        assert "overflow:clip" in body and "overflow:hidden" not in body, selector


def test_fixed_height_scroll_boxes_pin_their_header_to_their_own_top():
    assert ".chart-alt-table .table-scroll:not(.is-wide):not(.reg-scroll) > .table > thead th{top:0}" in PAGES
