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
    "duty_stats": ("duty_stats.html", "إحصائيات التشغيل",
                    "توازن وانتظام التشغيل الفعلي — عدالة التوزيع، تغطية الأهداف، والتقصيرات"),
    "board": ("board.html", "اليومية التفصيلية", "خدمات اليوم بأقسامها — الضباط والأفراد والمجندين"),
    "counts": ("counts.html", "أعداد الخدمات",
                "الخدمات الأساسية الصباحية والمسائية + إجمالي الطوارئ من اليومية التفصيلية"),
    "afraad": ("afraad.html", "يومية الأفراد",
                "الخدمات الأساسية الثابتة (دليل الخدمات) + الطارئة من اليومية التفصيلية"),
    "service_catalog": ("service_catalog.html", "دليل الخدمات",
                         "اسم كل خدمة أساسية وفترتها وقوامها المطلوب وتعليماتها"),
    "officer_log": ("officer_log.html", "سجل خدمات الضابط",
                     "List زمني لكل خدمة أو حالة للضابط في مدى تاريخ مختار"),
    "changes": ("changes.html", "سجل التغييرات",
                 "مين عدّل إيه وإمتى — بيتسجّل وقت تأكيد اليومية مش وقت الحفظ"),
    "missions": ("missions.html", "المأموريات",
                  "مأموريات لها دورة حياة (مخططة/بدأت/عادت/أغلقت) — مش خدمة متكررة"),
    "courses": ("courses.html", "الفِرق والدورات",
                 "الدورات اللي الضباط بياخدوها ومدة كل التحاق"),
    "register": ("register.html", "حصر تشغيل الضباط",
                  "موقف كل ضابط يوم بيوم — صف لكل ضابط وعمود لكل يوم"),
    "officer_register": ("officer_register.html", "دفتر الضابط",
                          "موقفه في كل يوم وحصر خدماته"),
    "leaves": ("leaves.html", "سجل الراحات",
                "سجل راحات الضباط — الأسبوعية والنصف شهرية والشهرية والاستثنائية"),
    "leaves_stats": ("leaves_stats.html", "إحصائيات الراحات",
                     "رسوم بيانية وإحصائيات تفصيلية لراحات وإجازات الضباط"),
    "leaves_monthly": ("leaves_monthly.html", "كشف الراحات الشهرية",
                        "تاريخ راحة واحد لكل ضابط شهري أو نصف شهري — يوصل من المديرية شهريًا"),
    "rest_suspension": ("rest_suspension.html", "وقف الراحات",
                        "أوامر وقف الراحات للضباط — ساري لحد «فتح الراحات»"),
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


@bp.get("/duty/stats")
def duty_stats():
    return _render("duty_stats")


@bp.get("/board")
def board():
    return _render("board")


@bp.get("/counts")
def counts():
    return _render("counts")


@bp.get("/afraad")
def afraad():
    return _render("afraad")


@bp.get("/service-catalog")
def service_catalog():
    return _render("service_catalog")


@bp.get("/officer-log")
def officer_log():
    return _render("officer_log")


@bp.get("/changes")
def changes():
    return _render("changes")


@bp.get("/missions")
def missions():
    return _render("missions")


@bp.get("/leaves")
def leaves():
    return _render("leaves")


@bp.get("/leaves/stats")
def leaves_stats():
    return _render("leaves_stats")


@bp.get("/leaves/monthly")
def leaves_monthly():
    return _render("leaves_monthly")


@bp.get("/leaves/suspension")
def rest_suspension():
    return _render("rest_suspension")


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
