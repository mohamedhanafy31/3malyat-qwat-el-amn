"""بحث اليوميات: الخانة موجودة في الصفحات الخمس، والسكربت متحمّل، والتلوين آمن للطباعة والداكن."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = {"/board": "#matchBoard", "/duty": "#dutyBoard", "/afraad": "#afWrap",
         "/campaign": "#campaignWrap", "/counts": "#cntBlocks"}


@pytest.mark.parametrize("url,root", PAGES.items())
def test_daily_pages_have_a_search_box_bound_to_their_table_root(client, url, root):
    html = client.get(url).get_data(as_text=True)

    assert "data-page-search" in html
    assert f'data-search-root="{root}"' in html
    assert "js/page-search.js" in html
    assert 'role="search"' in html
    assert "page-search-list" in html and "page-search-filter" in html


def test_search_script_folds_arabic_and_never_rewrites_the_dom():
    source = (ROOT / "static" / "js" / "page-search.js").read_text(encoding="utf-8")

    assert '"أ": "ا"' in source and '"ى": "ي"' in source and '"ة": "ه"' in source   # همزات/ياء/تاء مربوطة
    assert r"\u064B-\u065F" in source                                              # التشكيل
    assert "CSS.highlights" in source and "MutationObserver" in source
    # صفوف اليومية نفسها ما بتتعدلش (التظليل بالـHighlight API)؛ الـinnerHTML الوحيد لقايمة النتايج ومحتواها متهرّب
    assert source.count("innerHTML") == 1 and "list.innerHTML" in source
    assert "const esc = " in source and "&amp;" in source
    assert "requestAnimationFrame" not in source                                    # بيتوقف في التبويب المخفي


def test_highlight_styles_use_theme_tokens_and_vanish_in_print():
    css = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
    block = css[css.index("بحث داخل اليوميات"):]

    assert "tr.search-hit" in block and "!important" in block                      # بيغلب خلفيات الصفوف الخاصة
    assert ".page-search-box.is-floating" in block and "tr.search-miss" in block and "::highlight(page-search)" in block
    assert "#" not in "".join(line for line in block.splitlines() if "var(" not in line and ":" in line
                              and "color" in line)                                    # لا ألوان ثابتة
    assert "@media print" in block and "display:none" in block
