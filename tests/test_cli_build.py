import hashlib
import json
from pathlib import Path

import pytest

from dltools import cli

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def locks(tmp_path):
    for rel in ["static/latest/runtime", "python/3.12/runtime", "python/3.12/dev",
                "nginx/stable/runtime"]:
        p = tmp_path / "locks" / f"{rel}.apko.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return tmp_path / "locks"


def matrix(locks, changed, capsys, tmp_path):
    f = tmp_path / "changed.txt"
    f.write_text("\n".join(changed))
    assert cli.main(["matrix", "--locks", str(locks), "--changed", str(f)]) == 0
    return json.loads(capsys.readouterr().out)["include"]


def test_matrix_single_lock_change(locks, capsys, tmp_path):
    out = matrix(locks, ["locks/python/3.12/dev.lock.json"], capsys, tmp_path)
    assert out == [{"image": "python", "line": "3.12", "variant": "dev"}]


@pytest.mark.parametrize("path", [".trivyignore", ""])
def test_matrix_global_inputs_build_all(locks, capsys, tmp_path, path):
    assert len(matrix(locks, [path], capsys, tmp_path)) == 4


def test_matrix_removed_line_not_built(locks, capsys, tmp_path):
    assert matrix(locks, ["locks/python/3.10/runtime.lock.json"], capsys, tmp_path) == []


def test_lock_check_cli(capsys):
    assert cli.main(["lock-check", str(FIXTURES / "lock-clean.json")]) == 0
    assert cli.main(["lock-check", str(FIXTURES / "lock-snapshot.json")]) == 1
    assert "libexpat1" in capsys.readouterr().out


def test_tags_cli(tmp_path, capsys):
    state = tmp_path / "lines.json"
    state.write_text(json.dumps({"lines": [
        {"image": "python", "name": "3.12", "package": "python-3.12", "version": "3.12.15-r6"}]}))
    lock = tmp_path / "dev.lock.json"
    lock.write_text('{"a": 1}')
    h = hashlib.sha256(lock.read_bytes()).hexdigest()[:8]
    assert cli.main(["tags", "--state", str(state), "--image", "python", "--line", "3.12",
                     "--variant", "dev", "--lock", str(lock)]) == 0
    assert capsys.readouterr().out.split() == ["3.12-dev", "3.12.15-dev", f"3.12.15-{h}-dev"]


def test_tags_cli_takes_version_from_lock_not_state(tmp_path, capsys):
    # state already says 3.12.16 but the line's lock (blocked re-lock) still has 3.12.15
    state = tmp_path / "lines.json"
    state.write_text(json.dumps({"lines": [
        {"image": "python", "name": "3.12", "package": "python-3.12", "version": "3.12.16-r0"}]}))
    lock = tmp_path / "runtime.lock.json"
    lock.write_text(json.dumps({"contents": {"packages": [
        {"name": "python-3.12", "version": "3.12.15-r6", "architecture": a}
        for a in ("x86_64", "aarch64")]}}))
    assert cli.main(["tags", "--state", str(state), "--image", "python", "--line", "3.12",
                     "--variant", "runtime", "--lock", str(lock)]) == 0
    out = capsys.readouterr().out.split()
    assert out[:2] == ["3.12", "3.12.15"] and out[2].startswith("3.12.15-")


def test_lock_check_runtime_rejects_shell(tmp_path, capsys):
    lock = tmp_path / "l.json"
    lock.write_text(json.dumps({"contents": {"packages": [
        {"name": n, "version": "1.0-r0", "architecture": a}
        for a in ("x86_64", "aarch64") for n in ("python-3.12", "bash")]}}))
    assert cli.main(["lock-check", str(lock)]) == 0
    assert cli.main(["lock-check", "--runtime", str(lock)]) == 1
    assert "bash" in capsys.readouterr().out


@pytest.mark.parametrize("path", ["catalog.yaml", "packages/x86_64/APKINDEX.tar.gz",
                                  "melange/nginx-config.yaml", "melange.rsa.pub"])
def test_matrix_config_inputs_request_resync_instead_of_build(locks, capsys, tmp_path, path):
    f = tmp_path / "changed.txt"
    f.write_text(path)
    assert cli.main(["matrix", "--locks", str(locks), "--changed", str(f)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["resync"] is True and out["include"] == []


def test_matrix_trivyignore_rebuilds_all_without_resync(locks, capsys, tmp_path):
    f = tmp_path / "changed.txt"
    f.write_text(".trivyignore")
    cli.main(["matrix", "--locks", str(locks), "--changed", str(f)])
    out = json.loads(capsys.readouterr().out)
    assert out["resync"] is False and len(out["include"]) == 4


def test_state_revert_restores_previous_entry(tmp_path):
    cur = tmp_path / "lines.json"
    prev = tmp_path / "prev.json"
    entry = {"image": "python", "name": "3.12", "package": "python-3.12"}
    cur.write_text(json.dumps({"lines": [dict(entry, version="3.12.16-r0"),
                                         dict(entry, name="3.15", package="python-3.15",
                                              version="3.15.1-r0")]}))
    prev.write_text(json.dumps({"lines": [dict(entry, version="3.12.15-r6")]}))
    assert cli.main(["state-revert", "--state", str(cur), "--previous", str(prev),
                     "--image", "python", "--line", "3.12"]) == 0
    assert cli.main(["state-revert", "--state", str(cur), "--previous", str(prev),
                     "--image", "python", "--line", "3.15"]) == 0
    lines = json.loads(cur.read_text())["lines"]
    assert lines == [dict(entry, version="3.12.15-r6")]  # 3.15 was new: dropped
