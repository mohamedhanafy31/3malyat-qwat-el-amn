"""الصفحات المنفصلة و bootstrap المخصوص لكل صفحة."""
import pytest

PAGES = ["dashboard", "officers", "personnel", "target_commanders", "duty", "board",
         "counts", "leaves", "vehicles", "drivers", "campaign"]
URLS = {"dashboard": "/", "officers": "/officers", "personnel": "/personnel",
        "target_commanders": "/target-commanders",
        "duty": "/duty", "board": "/board", "counts": "/counts", "leaves": "/leaves",
        "vehicles": "/vehicles", "drivers": "/drivers", "campaign": "/campaign"}


@pytest.mark.parametrize("page", PAGES)
def test_each_page_renders_with_its_own_marker(client, page):
    r = client.get(URLS[page])
    assert r.status_code == 200
    assert f'data-page="{page}"' in r.get_data(as_text=True)


def test_every_page_contains_the_global_process_loader(client):
    html = client.get("/officers").get_data(as_text=True)
    assert 'id="processLoader"' in html
    assert 'id="processLoaderText"' in html
    assert "جاري التحميل" in html


def test_topbar_keeps_full_title_and_offers_compact_title(client):
    html = client.get("/officers").get_data(as_text=True)
    assert '<span class="title-full">مكتب العمليات وشؤون الضباط</span>' in html
    assert '<span class="title-compact" aria-hidden="true">مكتب العمليات</span>' in html


@pytest.mark.parametrize("template", ["login.html", "setup.html", "partials/user_modal.html"])
def test_password_toggles_stay_in_keyboard_order(template):
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent / "templates" / template).read_text(encoding="utf-8")
    toggles = source.split('data-toggle-password="')[1:]
    assert toggles
    assert all("tabindex" not in t.split(">")[0] for t in toggles)


def test_board_does_not_silently_drop_a_typed_person_selection():
    """كتابة الاسم في بحث الاختيار المتعدد من غير تثبيته كشارة ماينفعش
    يعدي كحفظ ناجح فاضي. المطابقة الكاملة تتثبت، والنص الجزئي يوقف الحفظ.
    """
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent / "static/js/board.js").read_text(encoding="utf-8")
    assert "function commandIds(" in source
    assert "اختر اسم ${singular} من قائمة النتائج قبل الحفظ" in source
    assert "if (personnelIds === null) return;" in source
    assert "personnel_ids: personnelIds" in source
    assert "return [];" in source, "خيار الرئاسة الفاضي لازم يتحفظ كشاغر"
    assert "officer_command_required:" in source
    assert "personnel_command_required:" in source
    assert "row?.officer_command_required" in source


def test_duty_modal_asks_for_an_emergency_end_day(client):
    """«طارئة» محتاجة «حتى يوم» في النموذج، وتفاصيل الفرقة بتتعرض في الصف."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = client.get("/duty").get_data(as_text=True)
    assert 'id="assignStatusEnd"' in html and "حتى يوم" in html
    duty = (root / "static/js/duty.js").read_text(encoding="utf-8")
    assert 'const BOUNDED_STATUSES = ["طارئة", "مأمورية", "انتداب"]' in duty
    assert "body.status_end = end" in duty
    assert "courseLine(r.course)" in duty
    assert "راحة فرقة" not in duty
    board = (root / "static/js/board.js").read_text(encoding="utf-8")
    assert "function outsiderDetail(" in board and "course.text" in board
    assert '[span, note].filter(Boolean).join(" — ")' in board


def test_board_groups_outsiders_in_operational_order():
    """الخوارج لا ترجع لجدول مختلط: الراحة مرتبة، والإجازات والفرق
    تتجمع بأسمائها الفعلية حتى تستوعب الأنواع الجديدة تلقائيًا.
    """
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent / "static/js/board.js").read_text(encoding="utf-8")
    assert "function outsiderGroups(" in source
    assert "outsiderGroupsView(sec.rows)" in source
    assert 'row.course?.name || "فرقة غير محددة"' in source
    assert "label: `فرقة: ${name}`" in source
    weekly = source.index('["أسبوعية", {label: "الراحات الأسبوعية", order: 0}]')
    half = source.index('["نصف شهرية", {label: "الراحات النصف شهرية", order: 1}]')
    monthly = source.index('["شهرية", {label: "الراحات الشهرية", order: 2}]')
    assert weekly < half < monthly
    assert 'return {key: `leave:${type}`, label: type, kind: "leave", order: 3}' in source


def test_board_renders_net_and_marks_taqseera_without_outsider_grouping():
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent / "static/js/board.js").read_text(encoding="utf-8")
    assert '"الصافي": [[' in source
    assert "const taqseeraMark =" in source and ">+ ت</b>" in source
    assert 'for (const name of ["الراحات", "الخوارج"])' in source
    assert '["الراحات", "التقصيرات", "الخوارج"]' not in source


@pytest.mark.parametrize("page", PAGES)
def test_bootstrap_returns_meta_for_every_page(client, page):
    d = client.get(f"/api/bootstrap/{page}").get_json()
    assert d["meta"]["today"]
    assert d["meta"]["command_roles"]
    assert set(["officers", "personnel", "leaves", "courses"]).issubset(d["counts"].keys())


def test_unknown_bootstrap_page_404s(client):
    assert client.get("/api/bootstrap/nope").status_code == 404


def test_campaign_page_has_export_and_bootstrap_days(client):
    html = client.get("/campaign").get_data(as_text=True)
    assert 'data-page="campaign"' in html
    assert 'data-export="docx"' in html
    payload = client.get("/api/bootstrap/campaign").get_json()
    assert payload["meta"]["today"] and "days" in payload


def test_pages_only_get_the_slice_they_need(client):
    """جوهر التحسين: مفيش صفحة بتحمّل داتا مش محتاجاها."""
    dash = client.get("/api/bootstrap/dashboard").get_json()
    assert "officers" not in dash and "leaves" not in dash and "personnel" not in dash
    assert dash["counts"]["officers"] == 2

    officers = client.get("/api/bootstrap/officers").get_json()
    assert "personnel" not in officers          # صفحة الضباط مالهاش دعوة بالأفراد
    assert "leaves" not in officers             # الحالة جاية محسوبة بدل السجلات

    counts_page = client.get("/api/bootstrap/counts").get_json()
    assert set(counts_page) <= {"meta", "days", "counts"}


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


def test_monthly_roster_has_direct_duration_and_cancel_controls(client):
    """الإنهاء/الإلغاء يظل مباشرًا من الصف، وتعديل المدة لا يختفي
    خلف قائمة إجراءات أو مودال آخر.
    """
    from pathlib import Path
    html = client.get("/leaves/monthly").get_data(as_text=True)
    source = (Path(__file__).resolve().parent.parent / "static/js/leaves-monthly.js").read_text(
        encoding="utf-8")
    assert 'id="stopLeaveModal"' in html
    assert "roster-days" in source
    assert "duration-readout" in source
    assert "roster-standard" in source
    assert "إلغاء الراحة" in source
    assert "إنهاء الآن" in source
    assert '!["active", "suspended"].includes(row.status)' in source


def test_new_leave_controls_keep_context_and_hide_irrelevant_cancel_date(client):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    duty_html = client.get("/duty").get_data(as_text=True)
    leaves_html = client.get("/leaves").get_data(as_text=True)
    stop_source = (root / "static/js/rest-stop.js").read_text(encoding="utf-8")
    assert "assign-state-card" in duty_html
    assert "status-behavior-hint" in duty_html
    assert "conditional-field" in leaves_html
    assert '$("#stopOnRow").classList.toggle("hidden", upcoming)' in stop_source
    assert '$("#stopOn").required = !upcoming' in stop_source


def test_arabic_is_not_escaped_in_json(client):
    """ensure_ascii=False — العربي بيتبعت UTF-8 مباشرة مش \\uXXXX،
    وده لوحده بيصغّر كل استجابة للنص تقريبًا."""
    raw = client.get("/api/bootstrap/officers").get_data(as_text=True)
    assert "أحمد" in raw
    assert "\\u0623" not in raw
