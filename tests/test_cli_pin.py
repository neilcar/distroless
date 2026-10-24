import json

import pytest
import yaml

from dltools import cli

INDEX = "P:zlib\nV:1.3.2-r7\n\nP:zlib\nV:1.3.2.1_rc20260921-r0\n\n"


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(cli, "fetch_index", lambda arch: INDEX)


def files(tmp_path, zlib_version):
    cfg = tmp_path / "runtime.apko.yaml"
    cfg.write_text(yaml.safe_dump({"contents": {"packages": ["python-3.12=3.12.15-r6"]}}))
    lock = tmp_path / "runtime.lock.json"
    lock.write_text(json.dumps({"contents": {"packages": [
        {"name": "zlib", "version": zlib_version, "architecture": a}
        for a in ("x86_64", "aarch64")]}}))
    return cfg, lock


def test_pin_released_rewrites_config(tmp_path, offline, capsys):
    cfg, lock = files(tmp_path, "1.3.2.1_rc20260921-r0")
    assert cli.main(["pin-released", "--config", str(cfg), "--lock", str(lock)]) == 3
    assert yaml.safe_load(cfg.read_text())["contents"]["packages"] == [
        "python-3.12=3.12.15-r6", "zlib=1.3.2-r7",
    ]
    assert "zlib=1.3.2-r7" in capsys.readouterr().out


def test_pin_released_clean_lock(tmp_path, offline):
    cfg, lock = files(tmp_path, "1.3.2-r7")
    before = cfg.read_text()
    assert cli.main(["pin-released", "--config", str(cfg), "--lock", str(lock)]) == 0
    assert cfg.read_text() == before


def test_pin_released_unresolvable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_index", lambda arch: "P:zlib\nV:1.3.2.1_rc1-r0\n\n")
    cfg, lock = files(tmp_path, "1.3.2.1_rc1-r0")
    assert cli.main(["pin-released", "--config", str(cfg), "--lock", str(lock)]) == 2
    assert "zlib" in capsys.readouterr().out
