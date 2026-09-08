"""الصفحات المنفصلة و bootstrap المخصوص لكل صفحة."""
import pytest

PAGES = ["dashboard", "officers", "personnel", "duty", "board", "catalog", "leaves"]
URLS = {"dashboard": "/", "officers": "/officers", "personnel": "/personnel",
        "duty": "/duty", "board": "/board", "catalog": "/catalog", "leaves": "/leaves"}


@pytest.mark.parametrize("page", PAGES)
def test_each_page_renders_with_its_own_marker(client, page):
    r = client.get(URLS[page])
    assert r.status_code == 200
    assert f'data-page="{page}"' in r.get_data(as_text=True)


@pytest.mark.parametrize("page", PAGES)
def test_bootstrap_returns_meta_for_every_page(client, page):
    d = client.get(f"/api/bootstrap/{page}").get_json()
    assert d["meta"]["today"]
    assert d["meta"]["command_roles"]


def test_unknown_bootstrap_page_404s(client):
    assert client.get("/api/bootstrap/nope").status_code == 404


def test_pages_only_get_the_slice_they_need(client):
    """جوهر التحسين: مفيش صفحة بتحمّل داتا مش محتاجاها."""
    dash = client.get("/api/bootstrap/dashboard").get_json()
    assert "officers" not in dash and "leaves" not in dash and "personnel" not in dash
    assert dash["counts"]["officers"] == 2

    officers = client.get("/api/bootstrap/officers").get_json()
    assert "personnel" not in officers          # صفحة الضباط مالهاش دعوة بالأفراد
    assert "leaves" not in officers             # الحالة جاية محسوبة بدل السجلات

    catalog = client.get("/api/bootstrap/catalog").get_json()
    assert set(catalog) <= {"meta", "services", "counts"}


def test_officer_status_is_computed_server_side(client):
    """عمود «حالة اليوم» بيوصل جاهز، فالواجهة مش محتاجة سجلات الراحات."""
    d = client.get("/api/bootstrap/officers").get_json()
    for o in d["officers"]["active"]:
        assert o["status_today"]["state"] in ("resting", "taqseera", "upcoming", "working")


def test_leaves_page_ships_rest_system_for_the_form(client):
    """نموذج الراحة بيملا اليوم والمدة تلقائيًا من نظام راحة الضابط."""
    d = client.get("/api/bootstrap/leaves").get_json()
    p = next(x for x in d["people"] if x["id"] == "OFF-001")
    assert p["rest_system"] == "أسبوعية" and p["rest_day"] == "السبت"


def test_arabic_is_not_escaped_in_json(client):
    """ensure_ascii=False — العربي بيتبعت UTF-8 مباشرة مش \\uXXXX،
    وده لوحده بيصغّر كل استجابة للنص تقريبًا."""
    raw = client.get("/api/bootstrap/officers").get_data(as_text=True)
    assert "أحمد" in raw
    assert "\\u0623" not in raw
