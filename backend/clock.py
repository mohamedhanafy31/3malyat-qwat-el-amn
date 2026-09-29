"""سلامة ساعة الجهاز — تنبيه لو رجعت لتاريخ قبل ما شافه السيستم قبل كده.

القفل التلقائي لليوم (`day_status.py`) والفتح الاستثنائي كلهم بيقارنوا
بـ«النهاردة» من ساعة الجهاز مباشرة، عن قصد (الجهاز معزول وممكن يتقفل
ويتفتح تاني من غير أي مجدول). لو ساعة الجهاز رجعت للخلف (بطارية CMOS
خلصت، أو حد غيّرها غلط) هذا الرجوع بيفكّ قفل أيام كانت مقفولة فعلًا من
غير أي حاجة تلفت النظر — العلامة هنا بتحفظ آخر «النهاردة» شافه السيستم
في ملف صغير برّه `data.json` (عشان ما تأثرش على تقسيم التخزين ولا
تتلمس مع كل حفظ خانة عادي)، وبتوري تحذير لو النهاردة الحقيقي دلوقتي
قبلها.
"""
from datetime import date

MARKER_NAME = ".clock_seen"


def _marker_path():
    from .store import DATA_DIR
    return DATA_DIR / MARKER_NAME


def check(today=None):
    """-> رسالة تحذير أو None. بتحدّث العلامة لو النهاردة اتقدّم — نداء
    واحد كل مرة الداشبورد بيتحمّل كفاية، مفيش داعي لمجدول."""
    today = (today or date.today()).isoformat()
    path = _marker_path()
    try:
        last = path.read_text(encoding="utf-8").strip()
    except OSError:
        last = ""

    if last and today < last:
        return (f"تاريخ الجهاز دلوقتي ({today}) قبل آخر تاريخ شغّل عليه السيستم "
                f"({last}) — القفل التلقائي لليوم ممكن يتأثر لو الساعة غلط.")

    if today > last:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(today, encoding="utf-8")
        except OSError:
            pass
    return None
