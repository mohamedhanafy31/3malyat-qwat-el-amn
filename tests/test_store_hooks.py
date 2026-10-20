from backend import store


def test_after_commit_hook_runs_and_errors_do_not_escape(monkeypatch):
    seen = []
    store.clear_after_commit_hooks()
    store.register_after_commit(lambda changes: seen.append(changes))
    store.register_after_commit(lambda changes: (_ for _ in ()).throw(RuntimeError("ignored")))
    store._run_after_commit(store.Changeset(frozenset({"2026-09-30"}), frozenset(), frozenset(), frozenset()))
    assert seen[0].days == frozenset({"2026-09-30"})
    store.clear_after_commit_hooks()


def test_changeset_is_immutable():
    changes = store.Changeset(frozenset(), frozenset(), frozenset(), frozenset({"officers"}))
    assert changes.core_keys == frozenset({"officers"})


def test_real_with_data_changeset_days_core_and_removed(data_file):
    seen = []
    store.clear_after_commit_hooks()
    store.register_after_commit(seen.append)
    day = "2026-09-30"

    def create(data):
        data.setdefault("day_assignments", {})[day] = [{"id": "AS-1"}]
        return "created"

    assert store.with_data(create, [day]) == "created"
    assert seen[-1].days == frozenset({day})
    assert seen[-1].created_days == frozenset({day})

    def change(data):
        data["day_assignments"][day][0]["name"] = "تعديل"

    store.with_data(change, [day])
    assert seen[-1].days == frozenset({day})
    assert seen[-1].created_days == frozenset()

    def remove(data):
        del data["day_assignments"][day]

    store.with_data(remove, [day])
    assert seen[-1].removed_days == frozenset({day})

    def core_change(data):
        data["officers"][0]["name"] = "اسم جديد"

    store.with_data(core_change)
    assert "officers" in seen[-1].core_keys
    store.clear_after_commit_hooks()


def test_noise_core_key_is_reported_but_hook_can_ignore_it(data_file):
    seen = []
    store.clear_after_commit_hooks()
    store.register_after_commit(seen.append)

    def mutate(data):
        data.setdefault("id_seq", {})["test"] = 1

    store.with_data(mutate)
    assert seen[-1].core_keys == frozenset({"id_seq"})
    store.clear_after_commit_hooks()


def test_hook_exception_never_breaks_real_save(data_file):
    store.clear_after_commit_hooks()
    store.register_after_commit(lambda _changes: (_ for _ in ()).throw(RuntimeError("boom")))

    def mutate(data):
        data.setdefault("service_tags", []).append("tag")

    assert store.with_data(mutate) is None
    store.clear_after_commit_hooks()


def test_hooks_and_worker_are_not_active_by_default():
    from backend import daily_files

    assert daily_files.worker() is None
