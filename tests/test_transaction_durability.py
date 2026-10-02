import json

from backend import store


def test_incomplete_journal_rolls_forward_and_is_idempotent(data_file):
    target = store.DATA_DIR / "days" / "2026" / "04" / "2026-04-10.json"
    replacement = {"assignments": [{"id": "AS-001", "name": " recovered "}]}
    store._write_journal([{
        "action": "replace",
        "target": "days/2026/04/2026-04-10.json",
        "text": json.dumps(replacement, ensure_ascii=False),
    }])

    assert store.recover_journal() is True
    assert json.loads(target.read_text(encoding="utf-8")) == replacement
    assert not store._journal_path().exists()
    assert store.recover_journal() is False


def test_journal_can_delete_a_file_after_a_partial_commit(data_file):
    target = store.day_path("2026-04-10")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"assignments": []}), encoding="utf-8")
    assert target.exists()
    store._write_journal([{"action": "delete", "target": str(target.relative_to(store.DATA_DIR))}])

    store.recover_journal()
    assert not target.exists()
    assert not store._journal_path().exists()
