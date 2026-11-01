from pathlib import Path

import pytest

from backend import export_preview


def test_confirm_other_days_defaults_on_and_is_in_meta(client):
    assert client.get("/api/settings").get_json()["settings"] == {"ops_confirm_other_days": True}
    meta = client.get("/api/bootstrap/dashboard").get_json()["meta"]
    assert meta["settings"]["ops_confirm_other_days"] is True


def test_admin_can_turn_confirmation_off(client):
    response = client.put("/api/settings", json={"ops_confirm_other_days": False})
    assert response.status_code == 200
    assert client.get("/api/settings").get_json()["settings"]["ops_confirm_other_days"] is False


def test_only_admin_can_change_settings(officer_client):
    assert officer_client.get("/api/settings").status_code == 200
    assert officer_client.put("/api/settings", json={"ops_confirm_other_days": False}).status_code == 403


@pytest.mark.parametrize("body", [{"unknown": True}, {"ops_confirm_other_days": "no"}])
def test_settings_reject_unknown_keys_and_non_bool(client, body):
    assert client.put("/api/settings", json=body).status_code == 400


def test_preview_rejects_non_office_payload(client):
    response = client.post("/api/export-preview?kind=docx", data=b"not a zip",
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 400


def test_preview_reports_unavailable_without_libreoffice(client, monkeypatch):
    monkeypatch.setattr(export_preview, "_binary", lambda: None)
    response = client.post("/api/export-preview?kind=docx", data=b"PK\x03\x04rest",
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 503
    assert response.get_json()["code"] == "preview_unavailable"


def test_preview_needs_login(anon_client):
    response = anon_client.post("/api/export-preview?kind=docx", data=b"PK",
                                headers={"X-Requested-With": "fetch"})
    assert response.status_code == 401


@pytest.mark.skipif(not export_preview.available(), reason="LibreOffice غير مثبّت")
def test_preview_converts_a_real_export_to_pdf(client):
    docx = client.get("/api/ops/2026-10-20/formation-morning.docx").data
    response = client.post("/api/export-preview?kind=docx", data=docx,
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200
    pages = response.get_json()["pages"]
    assert pages and all(page.startswith("data:image/png;base64,") for page in pages)


def test_every_export_goes_through_preview():
    sources = {name: Path("static/js", name).read_text(encoding="utf-8")
               for name in ("export.js", "leaves-monthly.js", "dashboard.js")}
    assert "previewExport(url, " in sources["export.js"]
    assert "location.assign" not in sources["leaves-monthly.js"]
    assert "previewExport(event.currentTarget.getAttribute(\"href\")" in sources["dashboard.js"]


def _signature_boxes(docx_bytes):
    import io, re, zipfile
    xml = zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode()
    boxes = []
    for box in re.findall(r"<w:txbxContent>.*?</w:txbxContent>", xml, re.S):
        lines = ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in re.findall(r"<w:p[ >].*?</w:p>", box, re.S)]
        if any(word in "".join(lines) for word in ("مدير", "وكي", "رئيس")):
            boxes.append(lines)
    return boxes


@pytest.mark.parametrize("url", ["/api/ops/2026-10-20/regularity.docx", "/api/duty/2026-10-20/export.docx"])
def test_signature_boxes_have_one_uniform_shape(client, url):
    boxes = _signature_boxes(client.get(url).data)
    assert boxes
    for lines in boxes:
        # المسمى، ثم «الرتبة/»، ثم «(الاسم)» — من غير \n جوه السطر ولا سطور فاضية.
        assert len(lines) == 3 and all(line and "\n" not in line for line in lines)
        assert lines[1].endswith("/") and lines[2].startswith("(") and lines[2].endswith(")")
    titles = {lines[0].replace("ـ", "") for lines in boxes}
    assert {"مدير إدارة قوات الأمن", "وكيل إدارة قوات الأمن", "رئيس قسم العمليات"} <= titles


def test_preview_prefers_word_and_falls_back_to_libreoffice(monkeypatch):
    monkeypatch.setattr(export_preview, "_office_installed", lambda: True)
    monkeypatch.setattr(export_preview, "_binary", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(export_preview, "_office_to_pdf", lambda content, kind: b"%PDF-word")
    monkeypatch.setattr(export_preview, "_libreoffice_to_pdf", lambda content, kind: b"%PDF-lo")
    assert export_preview.to_pdf(b"PK\x03\x04", "docx") == (b"%PDF-word", "word")

    def broken(content, kind):
        raise export_preview.PreviewUnavailable("office down")
    monkeypatch.setattr(export_preview, "_office_to_pdf", broken)
    assert export_preview.to_pdf(b"PK\x03\x04", "docx") == (b"%PDF-lo", "libreoffice")

    monkeypatch.setenv("EXPORT_PREVIEW_ENGINE", "word")
    with pytest.raises(export_preview.PreviewUnavailable):
        export_preview.to_pdf(b"PK\x03\x04", "docx")


def test_word_engine_never_used_off_windows(monkeypatch):
    monkeypatch.setattr(export_preview.os, "name", "posix")
    assert not export_preview._office_installed()
