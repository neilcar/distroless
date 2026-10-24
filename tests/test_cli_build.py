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


def test_matrix_catalog_change_builds_all(locks, capsys, tmp_path):
    out = matrix(locks, ["catalog.yaml"], capsys, tmp_path)
    assert len(out) == 4


@pytest.mark.parametrize("path", ["packages/x86_64/APKINDEX.tar.gz", ".trivyignore", ""])
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
