from backend import daily_files


def _result(day, kinds=None):
    return daily_files.DayFilesResult(
        day=day,
        folder="/tmp/daily",
        cloned_from=None,
        files={kind: {"ok": True, "path": f"/{kind}", "bytes": 1, "error": None}
                for kind in daily_files.KINDS},
    )


def test_status_and_refresh(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    monkeypatch.setattr(daily_files, "write_day_files", _result)

    status = client.get("/api/day-files/2026-09-30")
    assert status.status_code == 200
    assert status.get_json()["day"] == "2026-09-30"
    assert status.get_json()["enabled"] is True

    response = client.post("/api/day-files/2026-09-30/refresh", json={})
    assert response.status_code == 200
    assert set(response.get_json()["results"]) == set(daily_files.KINDS)


def test_status_bad_day_and_disabled_refresh(client, monkeypatch):
    assert client.get("/api/day-files/not-a-day").status_code == 400
    monkeypatch.setenv("DAILY_FILES_ENABLED", "false")
    assert client.post("/api/day-files/2026-09-30/refresh", json={}).status_code == 409


def test_refresh_range_validation_and_role(client, officer_client, monkeypatch):
    monkeypatch.setattr(daily_files, "write_day_files", _result)
    body = {"from": "2026-09-30", "to": "2026-10-01"}
    response = client.post("/api/day-files/refresh-range", json=body)
    assert response.status_code == 200
    assert response.get_json()["accepted"] == 2
    assert client.post(
        "/api/day-files/refresh-range",
        json={"from": "2020-01-01", "to": "2022-01-02"},
    ).status_code == 400
    assert officer_client.post("/api/day-files/refresh-range", json=body).status_code == 403


def test_board_page_contains_refresh_button(client):
    response = client.get("/board")
    assert response.status_code == 200
    assert b"btnRefreshFiles" in response.data
