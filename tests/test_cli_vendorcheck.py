import json
import subprocess
import urllib.error

from dltools import cli

VENDOR = {"vendor": [{"name": "darktable", "version": "5.6.2"}]}
NEWER = {"darktable": [{"tag_name": "release-5.6.3", "draft": False, "prerelease": False}]}


def run(tmp_path, monkeypatch, *extra, fetch=None, upsert=None):
    path = tmp_path / "vendor.json"
    path.write_text(json.dumps(VENDOR))
    calls = []
    monkeypatch.setattr(cli, "fetch_releases", fetch or (lambda v, t: NEWER))
    monkeypatch.setattr(cli, "fetch_pypi", lambda v: {})
    monkeypatch.setattr(cli, "upsert_issue", upsert or (lambda *a, **k: calls.append((a, k))))
    return cli.main(["vendor-check", "--vendor", str(path), *extra]), calls


def test_network_failure_warns_and_exits_zero(tmp_path, monkeypatch, capsys):
    def boom(v, t):
        raise urllib.error.URLError("down")
    code, calls = run(tmp_path, monkeypatch, fetch=boom)
    assert code == 0 and calls == []
    assert "warning" in capsys.readouterr().err


def test_gh_failure_warns_and_exits_zero(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "gh")
    code, _ = run(tmp_path, monkeypatch, upsert=boom)
    assert code == 0
    assert "warning" in capsys.readouterr().err


def test_dry_run_prints_and_never_notifies(tmp_path, monkeypatch, capsys):
    code, calls = run(tmp_path, monkeypatch, "--dry-run")
    assert code == 0 and calls == []
    assert "5.6.3" in capsys.readouterr().out
    code, calls = run(tmp_path, monkeypatch, "--dry-run", fetch=lambda v, t: {})
    assert calls == [] and "no newer releases" in capsys.readouterr().out


def test_notifies_with_dedupe(tmp_path, monkeypatch):
    code, calls = run(tmp_path, monkeypatch)
    assert code == 0 and len(calls) == 1 and calls[0][1] == {"dedupe": True}


def test_several_vendor_files_one_issue_with_wheels(tmp_path, monkeypatch):
    wheels = tmp_path / "stash.json"
    wheels.write_text(json.dumps({"vendor": [{
        "name": "stashapi", "version": "0.2.59", "kind": "wheel",
        "files": {"any": {"url": "https://x/stashapp_tools-0.2.59-py3-none-any.whl"}}}]}))
    tools = tmp_path / "pp.json"
    tools.write_text(json.dumps(VENDOR))
    calls = []
    monkeypatch.setattr(cli, "fetch_releases", lambda v, t: NEWER)
    monkeypatch.setattr(cli, "fetch_pypi", lambda v: {"stashapi": {"releases": {
        "0.2.60": [{"yanked": False}]}}} if v["vendor"][0]["name"] == "stashapi" else {})
    monkeypatch.setattr(cli, "upsert_issue", lambda *a, **k: calls.append((a, k)))
    assert cli.main(["vendor-check", "--vendor", str(tools), "--vendor", str(wheels)]) == 0
    (_title, body), kw = calls[0]
    assert len(calls) == 1 and kw == {"dedupe": True}
    assert "darktable: 5.6.3" in body and "stashapi: 0.2.60 is available on PyPI" in body
