from openpayer.ingest.run import pull


def test_pull_refuses_with_no_codes(monkeypatch, tmp_path, capsys):
    import openpayer.ingest.run as run

    monkeypatch.setattr(run, "load_codes", lambda: [])
    assert run.pull() == 2
    out = capsys.readouterr().out
    assert "Nothing is downloaded" in out or "nothing is downloaded" in out.lower()
