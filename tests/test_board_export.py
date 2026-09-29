"""تصدير اليومية التفصيلية كملف Word حقيقي (`/api/board/<day>/export.docx`)
— بيتولّد من نفس بيانات `/api/board` (`backend/board_export.py`)."""
import io

from docx import Document

DAY = "2026-04-10"


def _download(client, day=DAY):
    r = client.get(f"/api/board/{day}/export.docx")
    assert r.status_code == 200
    assert r.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Document(io.BytesIO(r.data))


def _all_text(doc):
    """`document.tables` بترجع الجداول العليا بس — جداول الأقسام متداخلة
    جوّه خانات جدول العمودين، فلازم ننزل جوّه كل خانة كمان."""
    out = []

    def walk_tables(tables):
        for t in tables:
            for row in t.rows:
                for cell in row.cells:
                    out.extend(p.text for p in cell.paragraphs)
                    walk_tables(cell.tables)

    walk_tables(doc.tables)
    return "\n".join(out)


def test_export_returns_a_real_docx_file(client):
    doc = _download(client)
    assert len(doc.tables) >= 1


def test_export_rejects_an_invalid_day(client):
    r = client.get("/api/board/not-a-day/export.docx")
    assert r.status_code == 400


def test_export_reflects_an_assigned_target_officer(client):
    client.put("/api/board/2026-04-10/target/سوميد", json={"officer_ids": ["OFF-001"]})
    doc = _download(client)
    assert "سوميد" in _all_text(doc)


def test_export_filename_carries_the_day(client):
    r = client.get(f"/api/board/{DAY}/export.docx")
    disposition = r.headers.get("Content-Disposition", "")
    assert DAY in disposition
