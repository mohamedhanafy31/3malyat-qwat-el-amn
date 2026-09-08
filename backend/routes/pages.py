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
    "duty": ("duty.html", "يومية التشغيل", "تشغيل الضباط اليومي وجدول الإجمالي"),
    "board": ("board.html", "لوحة التشغيل المختصرة", "مطابقة الخدمات اليومية — قابلة للتعديل الحر"),
    "catalog": ("catalog.html", "كتالوج الخدمات", "تصنيف الخدمات المستخدمة في جدول الإجمالي"),
    "leaves": ("leaves.html", "الراحات والإجازات",
                "سجل راحات الضباط — الأسبوعية والنصف شهرية والشهرية والاستثنائية"),
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
