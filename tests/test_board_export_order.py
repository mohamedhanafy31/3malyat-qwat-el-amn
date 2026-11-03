from backend.board_export import _latest_content


def _board():
    return {"date": "2026-11-03", "sections": [
        {"name": "الخدمات الطارئة", "type": "services", "rows": [
            {"id": "AS-2", "name": "خدمة متأخرة على الموقع", "time": "9ص"},
            {"id": "AS-1", "name": "خدمة بدري", "time": "7ص"},
        ]},
        {"name": "عمل بالإدارة", "type": "admin", "rows": [
            {"id": "OFF-3", "name": "ضابط نقيب", "role": "نقيب", "text": "متابعة 1"},
            {"id": "OFF-1", "name": "ضابط عقيد", "role": "عقيد", "text": "متابعة 2"},
            {"id": "OFF-2", "name": "ضابط رائد", "role": "رائد", "text": "متابعة 3"},
        ]},
    ]}


def _texts(rows):
    return [[cell["text"] for cell in row["cells"]] for row in rows]


def test_emergency_rows_keep_the_site_order_not_the_time_order():
    texts = _texts(_latest_content(_board()))
    names = [row[2] for row in texts[1:3]]
    assert names == ["خدمة متأخرة على الموقع", "خدمة بدري"]


def test_admin_work_is_ordered_by_rank_with_command_roles_first():
    texts = _texts(_latest_content(_board(), {"OFF-2": 0}))
    flat = [cell for row in texts for cell in row]
    positions = [next(i for i, text in enumerate(flat) if name in text)
                 for name in ("ضابط رائد", "ضابط عقيد", "ضابط نقيب")]
    assert positions == sorted(positions)
    plain = [cell for row in _texts(_latest_content(_board())) for cell in row]
    ranks = [next(i for i, text in enumerate(plain) if name in text)
             for name in ("ضابط عقيد", "ضابط رائد", "ضابط نقيب")]
    assert ranks == sorted(ranks)
