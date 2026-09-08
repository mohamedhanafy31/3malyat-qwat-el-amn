"""جدول الإجمالي اليومي — تصنيف كل ضابط في خانة واحدة بناءً على تشغيله."""
from .constants import SHIFTS, LEAVE_BUCKET
from .leaves import leave_on
from .people import officers_on


def summarise(data, day):
    """جدول الإجمالي أسفل يومية الضباط — كل ضابط في خانة واحدة بس."""
    services = {s["id"]: s for s in data["services"]}
    duties = data["duties"].get(day, {})
    officers = officers_on(data, day)

    s = {
        "أصل القوة": len(officers),
        "خارجية": {"صباحية": 0, "ليلية": 0, "بحث": 0},
        "داخلية": {"صباحية": 0, "ليلية": 0},
        "طبية": {"موجود": 0, "راحة": 0},
        "خوارج": {k: 0 for k in ("تقصيرة", "راحة", "طارئة", "غياب", "مرضي", "فرقة", "انتداب")},
        "حراسات": 0,
        "صافي": 0,
    }
    net_names, rows = [], []

    for o in officers:
        d = duties.get(o["id"], {})
        kinds = [(services.get(i.get("service_id"), {}), i.get("shift", "صباحية"))
                 for i in d.get("items", [])]
        lv = leave_on(data, o["id"], day)
        medical = any(sv.get("kind") == "طبية" for sv, _ in kinds)

        # الترتيب هنا هو نفس ترتيب الأولوية في اليومية الورقية
        if medical:
            bucket = ("طبية", "راحة" if lv else "موجود")
        elif lv:
            bucket = ("خوارج", LEAVE_BUCKET.get(lv["type"], "راحة"))
        elif d.get("status") in ("انتداب", "غياب"):
            bucket = ("خوارج", d["status"])
        elif d.get("taqseera"):
            bucket = ("خوارج", "تقصيرة")
        elif any(sv.get("kind") == "حراسات" for sv, _ in kinds):
            bucket = ("حراسات", None)
        elif any(sv.get("kind") == "داخلية" for sv, _ in kinds):
            sh = next(sh for sv, sh in kinds if sv.get("kind") == "داخلية")
            bucket = ("داخلية", sh if sh in SHIFTS else "صباحية")
        elif any(sv.get("kind") == "بحث" for sv, _ in kinds):
            bucket = ("خارجية", "بحث")
        elif any(sv.get("kind") == "خارجية" for sv, _ in kinds):
            sh = next(sh for sv, sh in kinds if sv.get("kind") == "خارجية")
            bucket = ("خارجية", sh if sh in SHIFTS else "صباحية")
        else:
            bucket = ("صافي", None)

        grp, sub = bucket
        if sub is None:
            s[grp] += 1
            if grp == "صافي":
                net_names.append(f'{o.get("role","")}/ {o.get("name","")}')
        else:
            s[grp][sub] += 1

        rows.append({
            "id": o["id"], "name": o.get("name", ""), "role": o.get("role", ""),
            "group": grp, "bucket": sub,
            "services": [{"id": sv.get("id"), "name": sv.get("name"), "kind": sv.get("kind"),
                          "shift": sh} for sv, sh in kinds if sv],
            "taqseera": bool(d.get("taqseera")),
            "leave": ({"type": lv["type"], "start": lv["start"], "end": lv["end"],
                      "return_date": lv["return_date"]} if lv else None),
            "note": d.get("note", ""),
            # كان بالقوة يوم كذا لكنه خرج بعد كده — للتوضيح في اليوميات القديمة
            "later_left": o.get("leave_date", "") or None,
        })

    counted = (sum(s["خارجية"].values()) + sum(s["داخلية"].values())
               + sum(s["طبية"].values()) + sum(s["خوارج"].values())
               + s["حراسات"] + s["صافي"])
    s["net_names"] = net_names
    s["balanced"] = counted == s["أصل القوة"]
    s["counted"] = counted
    return {"date": day, "summary": s, "rows": rows}
