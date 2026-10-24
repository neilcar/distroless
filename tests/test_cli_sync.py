import json
from pathlib import Path

import pytest

from dltools import cli

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(cli, "fetch_index", lambda arch: (FIXTURES / f"APKINDEX.{arch}").read_text())
    eol = json.loads((FIXTURES / "python-eol.json").read_text())
    monkeypatch.setattr(cli, "fetch_eol", lambda: eol)


def run_sync(tmp_path, capsys):
    rc = cli.main([
        "sync",
        "--state", str(tmp_path / "state/lines.json"),
        "--locks", str(tmp_path / "locks"),
        "--catalog", str(ROOT / "catalog.yaml"),
        "--today", "2026-10-24",
    ])
    out = capsys.readouterr().out
    return rc, [json.loads(line) for line in out.splitlines() if line.strip()]


def test_cli_sync_writes_state_and_configs(tmp_path, offline, capsys):
    rc, events = run_sync(tmp_path, capsys)
    assert rc == 0
    locks = tmp_path / "locks"
    for rel in [
        "static/latest/runtime.apko.yaml",
        "python/3.12/runtime.apko.yaml",
        "python/3.12/dev.apko.yaml",
        "python/3.15/dev.apko.yaml",
        "nginx/stable/runtime.apko.yaml",
        "nginx/mainline/runtime.apko.yaml",
    ]:
        assert (locks / rel).is_file(), rel
    assert not (locks / "python/3.10").exists()
    assert not (locks / "nginx/stable/dev.apko.yaml").exists()
    assert sum(e["kind"] == "line_added" for e in events) == 8  # static + 5 python + 2 nginx


def test_cli_sync_second_run_is_a_no_op(tmp_path, offline, capsys):
    run_sync(tmp_path, capsys)
    files = {p: p.read_bytes() for p in (tmp_path / "locks").rglob("*") if p.is_file()}
    rc, events = run_sync(tmp_path, capsys)
    assert rc == 0 and events == []
    assert {p: p.read_bytes() for p in (tmp_path / "locks").rglob("*") if p.is_file()} == files


def test_cli_sync_removes_dropped_line(tmp_path, offline, capsys):
    run_sync(tmp_path, capsys)
    stale = tmp_path / "locks/python/3.10"
    stale.mkdir()
    (stale / "runtime.lock.json").write_text("{}")
    state = json.loads((tmp_path / "state/lines.json").read_text())
    state["lines"].append({"image": "python", "name": "3.10", "package": "python-3.10",
                           "version": "3.10.22-r5"})
    (tmp_path / "state/lines.json").write_text(json.dumps(state))
    _, events = run_sync(tmp_path, capsys)
    assert [e["kind"] for e in events] == ["line_removed"]
    assert not stale.exists()
