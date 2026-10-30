"""مولدات موحّدة لملفات أرشيف اليوم."""

from copy import deepcopy

from . import campaign, counts
from .afraad import build_afraad
from .afraad_export import build_docx as build_afraad_docx
from .board import build_board
from .board_export import build_docx as build_board_docx, clinic_search_ids
from .campaign_export import build_docx as build_campaign_docx
from .day_open import needs_prepare, prepare
from .duty import summarise
from .duty_export import build_docx as build_duty_docx
from .regularity import build as build_regularity, effective_inputs
from .regularity_export import build_docx as build_regularity_docx
from .store import load_data
from .utils import around


def _bytes(value):
    """يحوّل BytesIO أو bytes إلى bytes."""
    return value.getvalue() if hasattr(value, "getvalue") else bytes(value)


def build_board_bytes(day):
    """يبني نسخة اللوحة المطابقة لمنطق preview في route
    اللوحة.
    """
    data = load_data(around(day, -1, 0))
    preview = deepcopy(data)
    if needs_prepare(data, day, include_inspections=True):
        prepare(preview, day, include_inspections=True)
    return _bytes(build_board_docx(build_board(preview, day), clinic_search_ids(preview, day)))


def build_duty_bytes(day):
    """يبني يومية الضباط من نفس نطاق ومسار العرض."""
    data = load_data(around(day, -1, 0))
    preview = deepcopy(data)
    if needs_prepare(data, day):
        prepare(preview, day)
    return _bytes(build_duty_docx(summarise(preview, day)))


def _afraad_scope(day):
    from .routes.afraad import _afraad_scope

    return _afraad_scope(day)


def build_afraad_bytes(day):
    """يبني يومية الأفراد من نطاق الأفراد الصريح."""
    data = load_data(_afraad_scope(day))
    return _bytes(build_afraad_docx(build_afraad(data, day)))


def build_campaign_bytes(day):
    """يبني يومية الحملة من نطاق الحملة الصريح."""
    from .routes.campaign import _scope

    data = load_data(_scope(day))
    return _bytes(build_campaign_docx(campaign.build_campaign(data, day)))


def build_counts_bytes(day):
    """يبني ملف أعداد الخدمات.

    غياب المصدّر يُعامل كنوع غير متاح أثناء التطوير.
    """
    try:
        from .counts_export import build_xlsx
    except ImportError as exc:
        raise RuntimeError("مولد أعداد الخدمات غير متاح بعد") from exc

    return _bytes(build_xlsx(counts.build(load_data([day]), day)))


def build_regularity_bytes(day):
    """يبني يومية الانتظام من نفس تجهيز الذاكرة المستخدم في مسار التصدير."""
    data = load_data(around(day, 0, -1, -2, -3))
    preview = deepcopy(data)
    if needs_prepare(data, day, include_inspections=True):
        prepare(preview, day, include_inspections=True)
    inputs, _ = effective_inputs(preview, day)
    payload = build_regularity(preview, day, inputs)
    payload["day"] = day
    return _bytes(build_regularity_docx(payload))
