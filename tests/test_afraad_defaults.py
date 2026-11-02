"""افتراضيات قوام/تسليح/انتظام الخدمات الأساسية."""
import json
from io import BytesIO

from docx import Document

from backend import afraad
from backend.text import core_service_name, norm

DAY = "2026-06-22"
SERVICE_ID = "AFB-01"
SERVICE_NAME = afraad.BASIC_SERVICE_NAMES[0]
DEFAULT = {"count": "مدرعة (3 مجند)", "weapon": "آلي + كلبش", "schedule": "8 ص / 8 م"}


def _defaults(monkeypatch):
    monkeypatch.setattr(afraad, "_default_services",
                        lambda: {norm(core_service_name(SERVICE_NAME)): dict(DEFAULT)})


def _row(client, day=DAY, entry_id=SERVICE_ID):
    rows = client.get(f"/api/afraad/{day}").get_json()["basic"]
    return next(row for row in rows if row["id"] == entry_id)


def _write_day(data_file, day, values):
    data = json.loads(data_file.read_text())
    data.setdefault("day_afraad", {}).setdefault(day, {})[SERVICE_ID] = values
    data_file.write_text(json.dumps(data, ensure_ascii=False))


def test_defaults_apply_without_day_or_previous_value(client, monkeypatch):
    _defaults(monkeypatch)
    row = _row(client)
    assert {key: row[key] for key in DEFAULT} == DEFAULT
    assert row["default_fields"] == ["count", "weapon", "schedule"]
    assert row["inherited_fields"] == []
    assert row["conscript_count"] == 3


def test_previous_day_wins_over_defaults(client, data_file, monkeypatch):
    _defaults(monkeypatch)
    previous = {"count": "سابق (2 مجند)", "weapon": "سلاح سابق",
                "schedule": "7 ص"}
    _write_day(data_file, "2026-06-21", previous)
    row = _row(client)
    assert {key: row[key] for key in DEFAULT} == previous
    assert row["inherited_fields"] == ["count", "weapon", "schedule"]
    assert row["default_fields"] == []
    assert row["inherited_from"] == "2026-06-21"


def test_day_override_including_explicit_empty_wins(client, data_file, monkeypatch):
    _defaults(monkeypatch)
    _write_day(data_file, DAY, {"count": "", "weapon": "سلاح اليوم", "schedule": ""})
    row = _row(client)
    assert row["count"] == "" and row["schedule"] == ""
    assert row["weapon"] == "سلاح اليوم"
    assert row["default_fields"] == []


def test_unknown_service_gets_no_defaults(client, data_file, monkeypatch):
    _defaults(monkeypatch)
    data = json.loads(data_file.read_text())
    data.setdefault("reference_lists", {})["afraad_basic"] = [{
        "from": "2026-01-01", "items": [{"id": "AFB-X", "name": "خدمة جديدة"}],
    }]
    data_file.write_text(json.dumps(data, ensure_ascii=False))
    row = _row(client, entry_id="AFB-X")
    assert row["count"] == row["weapon"] == row["schedule"] == ""
    assert row["default_fields"] == []


def test_export_shows_default_values(client, monkeypatch):
    _defaults(monkeypatch)
    response = client.get(f"/api/afraad/{DAY}/export.docx")
    assert response.status_code == 200
    document = Document(BytesIO(response.data))
    text = "\n".join(cell.text for table in document.tables
                     for row in table.rows for cell in row.cells)
    assert all(value in text for value in DEFAULT.values())
