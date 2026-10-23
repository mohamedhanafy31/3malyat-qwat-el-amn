"""الأسماء العربية المختصرة لأحداث ومسارات سجل النشاط."""
import re

EVENT_LABELS = {
    "write": "تعديل بيانات", "login_ok": "تسجيل دخول",
    "login_failed": "محاولة دخول فاشلة", "logout": "تسجيل خروج",
    "user_created": "إنشاء حساب", "user_updated": "تعديل حساب",
    "password_changed": "تغيير كلمة المرور", "password_reset": "إعادة تعيين كلمة المرور",
    "access_denied": "محاولة وصول مرفوضة", "setup_admin": "إنشاء أول مدير",
}

AUTH_ACTIONS = {key: label for key, label in EVENT_LABELS.items() if key != "write"}

# الترتيب من الأخص للأعم. التعبيرات تغطي عائلات المسارات بدل جدول طويل هش.
ROUTES = [
    (r"^POST /api/roster-import/conscripts/apply$", "استبدال كشف المجندين السائقين"),
    (r"^POST /api/roster-import/personnel/apply$", "استبدال كشف الأفراد"),
    (r"^POST /api/person$", "إضافة فرد"),
    (r"^PATCH /api/person/", "تعديل بيانات فرد"),
    (r"^DELETE /api/person/", "حذف فرد"),
    (r"^POST /api/person/.*/(remove|restore)$", "تغيير حالة فرد"),
    (r"^POST /api/assignments/", "إضافة تكليف"),
    (r"^PATCH /api/assignments/", "تعديل تكليف"),
    (r"^DELETE /api/assignments/", "حذف تكليف"),
    (r"^(PUT|POST|PATCH|DELETE) /api/board/", "تعديل اليومية التفصيلية"),
    (r"^(PUT|POST|PATCH|DELETE) /api/duty/", "تعديل يومية الضباط"),
    (r"^(PUT|POST|PATCH|DELETE) /api/afraad/", "تعديل يومية الأفراد"),
    (r"^(POST|PATCH|DELETE) /api/leaves", "تعديل سجل الراحات"),
    (r"^(POST|PATCH|DELETE) /api/missions", "تعديل مأمورية"),
    (r"^(POST|PATCH|DELETE) /api/vehicles", "تعديل سجل المركبات"),
    (r"^(POST|PATCH|DELETE) /api/conscripts", "تعديل سجل المجندين"),
    (r"^(PUT|POST|DELETE) /api/campaign/", "تعديل يومية الحملة"),
    (r"^(POST|PATCH|DELETE) /api/course", "تعديل فرقة أو دورة"),
    (r"^(POST|PATCH|DELETE) /api/counts", "تعديل أعداد الخدمات"),
    (r"^(POST|PATCH|DELETE) /api/service-catalog", "تعديل دليل الخدمات"),
    (r"^(POST|PATCH|DELETE) /api/rest-suspensions", "تعديل وقف الراحات"),
    (r"^(POST|PATCH|DELETE) /api/inspection-schedule", "تعديل جدول التفتيش"),
    (r"^PATCH /api/command", "تعديل بيانات القيادة"),
    (r"^POST /api/day-status/", "تغيير حالة اليوم"),
    (r"^POST /api/day-files/", "تحديث الملفات اليومية"),
    (r"^POST /api/ops/.*/depart$", "قيام خدمة"),
    (r"^POST /api/ops/.*/return$", "عودة خدمة"),
    (r"^POST /api/ops/.*/undo$", "تراجع تشغيل خدمة"),
    (r"^PATCH /api/ops/.*/time$", "تعديل معاد خدمة"),
]


def action_label(event, method, path):
    if event in AUTH_ACTIONS:
        return AUTH_ACTIONS[event]
    value = f"{method or ''} {path or ''}".strip()
    for pattern, label in ROUTES:
        if re.search(pattern, value):
            return label
    return value
