import json

import pytest

from dltools import cli

INDEX = "P:x\nV:1.0-r0\n\nP:py\nV:3.13.15-r8\n\n"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(cli, "fetch_index", lambda arch: INDEX)


def write(tmp_path, name, vulns):
    p = tmp_path / name
    p.write_text(json.dumps({"Results": [{"Vulnerabilities": [
        {"VulnerabilityID": i, "Severity": s, "FixedVersion": f, "PkgName": "x"} for i, s, f in vulns
    ]}]}))
    return str(p)


def test_cli_gate_fails_on_fixable_high(tmp_path, capsys):
    cand = write(tmp_path, "c.json", [("CVE-1", "HIGH", "1.0")])
    rc = cli.main(["gate", "--candidate", cand, "--ignore", str(tmp_path / "none"),
                   "--label", "python:3.12 amd64"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out and "CVE-1" in out and "python:3.12 amd64" in out


def test_cli_gate_passes_against_published(tmp_path, capsys):
    cand = write(tmp_path, "c.json", [("CVE-2", "LOW", "")])
    pub = write(tmp_path, "p.json", [("CVE-2", "LOW", "")])
    rc = cli.main(["gate", "--candidate", cand, "--published", pub,
                   "--ignore", str(tmp_path / "none"), "--label", "x"])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_gate_snapshot_only_fix_does_not_block(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"Results": [{"Vulnerabilities": [
        {"VulnerabilityID": "CVE-9", "Severity": "HIGH", "PkgName": "py",
         "FixedVersion": "3.13.15_git20260912-r0"}]}]}))
    rc = cli.main(["gate", "--candidate", str(p), "--ignore", str(tmp_path / "none"),
                   "--label", "py"])
    out = capsys.readouterr().out
    assert rc == 0 and "no released fix" in out
