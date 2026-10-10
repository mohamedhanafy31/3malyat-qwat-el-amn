from urllib.parse import quote


def test_forged_edited_by_header_does_not_break_request(client):
    """الترويسة القديمة لو وصلت من عميل قديم تتجاهلها الخدمة."""
    r = client.post("/api/assignments/2026-04-10",
                     json={"name": "خدمة تدقيق", "kind": "خارجية"},
                     headers={"X-Edited-By": quote("اختبار المراجعة")})
    assert r.status_code == 201


def test_audit_log_records_real_user_and_ignores_header(client, tmp_path):
    from backend import store
    log_file = tmp_path / "audit.log"
    import logging
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    store._audit_logger.handlers = [handler]

    client.post("/api/assignments/2026-04-10", json={"name": "خدمة٢", "kind": "خارجية"},
                headers={"X-Edited-By": quote("محمد")})
    handler.flush()
    handler.close()

    content = log_file.read_text(encoding="utf-8")
    assert "مدير الاختبارات" in content
    assert "محمد" not in content
