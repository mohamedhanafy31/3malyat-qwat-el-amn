import gzip
import json

GZ = {"Accept-Encoding": "gzip, deflate, br"}


def test_json_is_gzipped_when_client_accepts_it(client):
    plain = client.get("/api/bootstrap/officers")
    packed = client.get("/api/bootstrap/officers", headers=GZ)
    assert "Content-Encoding" not in plain.headers
    assert packed.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in packed.headers["Vary"]
    assert json.loads(gzip.decompress(packed.data)) == plain.get_json()
    assert len(packed.data) < len(plain.data)


def test_versioned_static_is_cached_for_a_year_and_compressed(client):
    res = client.get("/static/style.css?v=1", headers=GZ)
    assert res.status_code == 200
    cc = res.headers["Cache-Control"]
    assert "max-age=31536000" in cc and "immutable" in cc and "no-cache" not in cc
    assert res.headers["Content-Encoding"] == "gzip"
    with open("static/style.css", "rb") as fh:
        assert gzip.decompress(res.data) == fh.read()
    # الضغط بيتعمل مرة واحدة ويتخزّن
    again = client.get("/static/style.css?v=1", headers=GZ)
    assert again.data == res.data


def test_unversioned_static_keeps_revalidation(client):
    res = client.get("/static/fonts/NotoSansArabic-400.woff2", headers=GZ)
    assert "immutable" not in res.headers.get("Cache-Control", "")
    # الخطوط مضغوطة أصلًا — مفيش gzip فوقها
    assert "Content-Encoding" not in res.headers


def test_word_export_is_not_gzipped(client):
    res = client.get("/api/board/2026-04-10/export.docx", headers=GZ)
    assert res.status_code == 200 and res.data[:2] == b"PK"
    assert "Content-Encoding" not in res.headers


def test_static_version_stamp_follows_file_changes(client, tmp_path, monkeypatch):
    """الملفات الثابتة متخزّنة سنة عند المتصفح، فالختم لازم يتغيّر أول ما الملف
    يتغيّر — حتى من غير إعادة تشغيل السيستم."""
    import os
    from app import app
    static = tmp_path / "static"
    static.mkdir()
    (static / "x.css").write_text("a")
    monkeypatch.setattr(app, "static_folder", str(static))
    with app.test_request_context():
        from flask import url_for
        os.utime(static / "x.css", (1_000_000, 1_000_000))
        first = url_for("static", filename="x.css")
        os.utime(static / "x.css", (2_000_000, 2_000_000))
        second = url_for("static", filename="x.css")
    assert first.endswith("v=1000000") and second.endswith("v=2000000")
