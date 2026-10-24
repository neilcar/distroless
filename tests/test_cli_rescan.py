import json

from dltools import cli


def test_cli_rescan_decide(tmp_path, capsys):
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"Results": [{"Vulnerabilities": [
        {"VulnerabilityID": "CVE-1", "Severity": "HIGH", "FixedVersion": "", "PkgName": "p"}]}]}))
    prev = tmp_path / "prev.txt"
    prev.write_text("")
    rc = cli.main(["rescan-decide", "--report", str(rep), "--ignore", str(tmp_path / "none"),
                   "--previous", str(prev)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["open_issue"] is True and out["rebuild"] is False
    assert out["ids"] == ["CVE-1"]


def test_cli_rescan_decide_missing_previous_file(tmp_path, capsys):
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"Results": []}))
    rc = cli.main(["rescan-decide", "--report", str(rep), "--ignore", str(tmp_path / "none"),
                   "--previous", str(tmp_path / "absent.txt")])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["open_issue"] is False


def test_cli_notify_calls_upsert(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "upsert_issue", lambda title, body: seen.update(t=title, b=body))
    assert cli.main(["notify", "--title", "Build failed: x", "--body", "url"]) == 0
    assert seen == {"t": "Build failed: x", "b": "url"}
