import sys

from tools import deploy_log


def test_emit_prints_and_appends_to_the_deployment_log(tmp_path, monkeypatch, capsys):
    log = tmp_path / "deploy.log"
    monkeypatch.setenv("DEPLOY_LOG", str(log))

    deploy_log.emit("downloading", "INFO")
    deploy_log.emit("it broke", "X")

    shown = capsys.readouterr().out
    logged = log.read_text(encoding="utf-8").splitlines()
    assert "downloading" in shown and "[X] it broke" in shown
    assert logged[1] == "[X] it broke"  # starts with [X] so deploy_console.bat `failures` finds it
    assert "[INFO] downloading" in logged[0]


def test_emit_survives_a_missing_log_and_non_ascii_text(monkeypatch, capsys):
    monkeypatch.delenv("DEPLOY_LOG", raising=False)
    deploy_log.emit("path \u0633\u064a\u0633\u062a\u0645", "OK")
    assert "OK" in capsys.readouterr().out


def test_stream_run_echoes_every_line_and_reports_the_exit_code(tmp_path, monkeypatch, capsys):
    log = tmp_path / "deploy.log"
    monkeypatch.setenv("DEPLOY_LOG", str(log))
    code = "import sys; print('one'); print('two', file=sys.stderr); sys.exit(3)"

    result = deploy_log.stream_run([sys.executable, "-c", code], label="Test run")

    assert result.returncode == 3
    assert result.tail == ["one", "two"]
    text = log.read_text(encoding="utf-8")
    assert "| one" in text and "| two" in text
    assert "exit code 3" in text
    assert "| one" in capsys.readouterr().out


def test_stream_run_times_out_and_kills_the_process(tmp_path, monkeypatch):
    monkeypatch.delenv("DEPLOY_LOG", raising=False)

    result = deploy_log.stream_run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)

    assert result.timed_out is True
    assert result.returncode == -9


def test_stream_run_reports_a_missing_program(monkeypatch):
    monkeypatch.delenv("DEPLOY_LOG", raising=False)

    result = deploy_log.stream_run(["definitely-not-a-real-program-xyz"])

    assert result.returncode == 127
