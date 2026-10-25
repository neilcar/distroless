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


def test_cli_gate_vendor_prefix_moves_findings_out_of_the_gate(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"Results": [{"Target": "opt/yt-dlp/yt-dlp", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-5", "Severity": "CRITICAL", "PkgName": "openssl",
         "FixedVersion": "3.5.9"}]}]}))
    rc = cli.main(["gate", "--candidate", str(p), "--ignore", str(tmp_path / "none"),
                   "--vendor-prefix", "/opt/darktable", "--vendor-prefix", "/opt/yt-dlp",
                   "--label", "pp"])
    out = capsys.readouterr().out
    assert rc == 0 and "Vendored (not gated)" in out and "CVE-5" in out


def test_cli_gate_vendor_json_sets_prefixes_and_caveat(tmp_path, capsys):
    vj = tmp_path / "vendor.json"
    vj.write_text(json.dumps({"vendor": [
        {"name": "darktable", "version": "5.6.2", "prefix": "/opt/darktable"},
        {"name": "yt-dlp", "version": "2026.10.21", "prefix": "/opt/yt-dlp"}]}))
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"Results": [{"Target": "opt/yt-dlp/yt-dlp", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-5", "Severity": "CRITICAL", "PkgName": "openssl",
         "FixedVersion": "3.5.9"}]}]}))
    rc = cli.main(["gate", "--candidate", str(p), "--ignore", str(tmp_path / "none"),
                   "--vendor", str(vj), "--label", "pp"])
    out = capsys.readouterr().out
    assert rc == 0 and "CVE-5" in out.split("Vendored (not gated)", 1)[1]
    assert "(darktable 5.6.2, yt-dlp 2026.10.21)" in out


def test_cli_gate_wheels_are_gated_not_vendored(tmp_path, capsys):
    # A wheel's findings (python-pkg under site-packages) count like any package; only the
    # AppImage/binary entries are listed apart, and only they are named in the caveat.
    site = "/usr/lib/python3.12/site-packages"
    vj = tmp_path / "vendor.json"
    vj.write_text(json.dumps({"vendor": [
        {"name": "yt-dlp", "version": "2026.10.21", "kind": "binary", "prefix": "/opt/yt-dlp"},
        {"name": "cloudscraper", "version": "1.2.71", "kind": "wheel", "prefix": site}]}))
    pub = tmp_path / "p.json"
    pub.write_text(json.dumps({"Results": []}))
    cand = tmp_path / "c.json"
    cand.write_text(json.dumps({"Results": [{"Target": "Python", "Type": "python-pkg",
        "Vulnerabilities": [{"VulnerabilityID": "CVE-7", "Severity": "MEDIUM",
                             "PkgName": "cloudscraper", "InstalledVersion": "1.2.71",
                             "PkgPath": "usr/lib/python3.12/site-packages/"
                                        "cloudscraper-1.2.71.dist-info/METADATA"}]}]}))
    rc = cli.main(["gate", "--candidate", str(cand), "--published", str(pub),
                   "--ignore", str(tmp_path / "none"), "--vendor", str(vj), "--label", "sb"])
    out = capsys.readouterr().out
    gated, vendored = out.split("Vendored (not gated)", 1)
    assert rc == 1  # one more MEDIUM than the published image: the not-worse rule applies
    assert "| MEDIUM | 1 | 0 |" in gated and "CVE-7" not in vendored
    assert "(yt-dlp 2026.10.21)" in vendored and "cloudscraper" not in vendored


def test_cli_gate_wheels_only_vendor_json_has_no_vendored_section(tmp_path, capsys):
    vj = tmp_path / "vendor.json"
    vj.write_text(json.dumps({"vendor": [{"name": "stashapi", "version": "0.2.59", "kind": "wheel",
                                          "prefix": "/usr/lib/python3.12/site-packages"}]}))
    cand = tmp_path / "c.json"
    cand.write_text(json.dumps({"Results": []}))
    assert cli.main(["gate", "--candidate", str(cand), "--ignore", str(tmp_path / "none"),
                     "--vendor", str(vj)]) == 0
    assert "Vendored (not gated)" not in capsys.readouterr().out
