"""صفحات HTML — كل قسم بقى صفحة مستقلة بـURL خاص بيها.

قبل كده كان كل النظام صفحة واحدة والأقسام بتتخفي وتظهر بالجافاسكريبت،
فأي ريفرش كان بيرجّعك للرئيسية ويضيّع مكانك. دلوقتي كل صفحة ليها لينك
حقيقي — الريفرش بيفضّلك مكانك، وزراير الرجوع/التقدّم في المتصفح بتشتغل،
وكل صفحة بتحمّل الـHTML والجافاسكريبت والداتا بتاعتها هي بس.
"""
from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)

# key -> (template, عنوان الصفحة, الوصف تحته, مفتاح التبويب النشط في القايمة)
PAGES = {
    "dashboard": ("dashboard.html", "الرئيسية", "نظرة عامة على القوة والتشغيل اليوم"),
    "officers": ("force.html", "الضباط", "سجل الضباط والأرشيف"),
    "personnel": ("force.html", "الأفراد", "سجل الأفراد والأرشيف"),
    "duty": ("duty.html", "يومية الضباط", "تشغيل الضباط اليومي وجدول الإجمالي"),
    "board": ("board.html", "اليومية التفصيلية", "خدمات اليوم بأقسامها — الضباط والأفراد والمجندين"),
    "catalog": ("catalog.html", "كتالوج الخدمات", "تصنيف الخدمات المستخدمة في جدول الإجمالي"),
    "courses": ("courses.html", "الفِرق والدورات",
                 "الدورات اللي الضباط بياخدوها ومدة كل التحاق"),
    "register": ("register.html", "دفتر 43",
                  "موقف كل ضابط يوم بيوم — صف لكل ضابط وعمود لكل يوم"),
    "officer_register": ("officer_register.html", "دفتر الضابط",
                          "موقفه في كل يوم وحصر خدماته"),
    "leaves": ("leaves.html", "الراحات والإجازات",
                "سجل راحات الضباط — الأسبوعية والنصف شهرية والشهرية والاستثنائية"),
    "leaves_stats": ("leaves_stats.html", "إحصائيات الراحات",
                     "رسوم بيانية وإحصائيات تفصيلية لراحات وإجازات الضباط"),
    "leaves_monthly": ("leaves_monthly.html", "تحديث كشف الراحات الشهرية",
                        "تاريخ راحة واحد لكل ضابط شهري أو نصف شهري — يوصل من المديرية شهريًا"),
}


def _render(page):
    template, title, subtitle = PAGES[page]
    return render_template(f"pages/{template}", page=page, page_title=title,
                            page_subtitle=subtitle)


@bp.get("/")
def dashboard():
    return _render("dashboard")


@bp.get("/officers")
def officers():
    return _render("officers")


@bp.get("/personnel")
def personnel():
    return _render("personnel")


@bp.get("/duty")
def duty():
    return _render("duty")


@bp.get("/board")
def board():
    return _render("board")


@bp.get("/catalog")
def catalog():
    return _render("catalog")


@bp.get("/leaves")
def leaves():
    return _render("leaves")


@bp.get("/leaves/stats")
def leaves_stats():
    return _render("leaves_stats")


@bp.get("/leaves/monthly")
def leaves_monthly():
    return _render("leaves_monthly")


@bp.get("/courses")
def courses():
    return _render("courses")


@bp.get("/register")
def register():
    return _render("register")


@bp.get("/register/<officer_id>")
def officer_register(officer_id):
    template, title, subtitle = PAGES["officer_register"]
    return render_template(f"pages/{template}", page="register", page_title=title,
                            page_subtitle=subtitle, officer_id=officer_id)
