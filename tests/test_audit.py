from urllib.parse import quote


def test_arabic_edited_by_header_does_not_break_request(client):
    """المتصفح لازم يبعت X-Edited-By مشفّر (encodeURIComponent) لأن ترويسة HTTP
    لازم تبقى ISO-8859-1 بس — عربي خام كان بيكسر fetch() نفسه في الفرونت إند
    قبل ما الطلب يتبعت أصلًا (اكتشفناها لايف: أي تعديل كان بيفشل بصمت لو حقل
    "اسمك" فيه نص عربي، يعني كل الوقت عمليًا)."""
    r = client.post("/api/services",
                     json={"name": "خدمة تدقيق", "kind": "خارجية"},
                     headers={"X-Edited-By": quote("اختبار المراجعة")})
    assert r.status_code == 201


def test_audit_log_records_decoded_name(client, tmp_path):
    from backend import store
    log_file = tmp_path / "audit.log"
    import logging
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    store._audit_logger.handlers = [handler]

    client.post("/api/services", json={"name": "خدمة٢", "kind": "خارجية"},
                headers={"X-Edited-By": quote("محمد")})
    handler.flush()
    handler.close()

    content = log_file.read_text(encoding="utf-8")
    assert "محمد" in content
