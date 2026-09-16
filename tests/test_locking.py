import json
import threading


def test_abort_does_not_persist(client, data_file):
    before = json.loads(data_file.read_text(encoding="utf-8"))
    r = client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "تصنيف غير موجود"})
    assert r.status_code == 400
    after = json.loads(data_file.read_text(encoding="utf-8"))
    assert before == after, "طلب مرفوض (AbortRequest) لازم ميغيرش أي حاجة في data.json"


def test_concurrent_writes_preserve_all_updates(client):
    """قبل with_data(): طلبين متزامنين كانوا ممكن يحمّلوا نفس النسخة، يعدّلوا
    كل واحد لوحده، وآخر save يمسح تعديل التاني من غير قصد."""
    results = []

    def add_one(i):
        r = client.post("/api/leaves", json={
            "person_id": "OFF-002", "type": "أسبوعية",
            "start": f"2026-02-{i:02d}", "end": f"2026-02-{i:02d}"})
        results.append(r.get_json())

    threads = [threading.Thread(target=add_one, args=(i + 1,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = [r["id"] for r in results if r and "id" in r]
    assert len(ids) == 6
    assert len(set(ids)) == 6, "لازم كل الأيدي فريدة — مفيش تصادم"

    final = client.get("/api/data").get_json()
    starts = {l["start"] for l in final["leaves"] if l["person_id"] == "OFF-002"}
    expected = {f"2026-02-{i + 1:02d}" for i in range(6)}
    assert expected.issubset(starts), "أي تحديث ضاع معناه في بيانات مفقودة هنا"
