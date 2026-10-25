import subprocess
from pathlib import Path

from dltools import cli

FIXTURES = Path(__file__).parent / "fixtures"


def run(tmp_path, monkeypatch, version, *extra, upsert=None):
    cfg = tmp_path / "distroless-libvips.yaml"
    cfg.write_text(f'package:\n  name: distroless-libvips\n  version: "{version}"\n  epoch: 0\n')
    calls = []
    monkeypatch.setattr(cli, "fetch_index", lambda arch: (FIXTURES / f"APKINDEX.{arch}").read_text())
    monkeypatch.setattr(cli, "upsert_issue", upsert or (lambda *a, **k: calls.append((a, k))))
    return cli.main(["libvips-check", "--melange", str(cfg), *extra]), calls


def test_up_to_date_does_not_notify(tmp_path, monkeypatch, capsys):
    code, calls = run(tmp_path, monkeypatch, "8.18.7")
    assert code == 0 and calls == []
    assert "up to date" in capsys.readouterr().out


def test_behind_notifies_one_deduped_issue(tmp_path, monkeypatch):
    code, calls = run(tmp_path, monkeypatch, "8.18.6")
    assert code == 0 and len(calls) == 1
    (title, body), kwargs = calls[0]
    assert title == "distroless-libvips is behind Wolfi libvips 8.18.7"
    assert "8.18.6" in body and "melange/distroless-libvips.yaml" in body
    assert kwargs == {"dedupe": True}
    # The body is the same on every run, so dedupe can skip repeat comments.
    _, again = run(tmp_path, monkeypatch, "8.18.6")
    assert again == calls


def test_dry_run_prints_and_never_notifies(tmp_path, monkeypatch, capsys):
    code, calls = run(tmp_path, monkeypatch, "8.18.6", "--dry-run")
    assert code == 0 and calls == []
    assert "distroless-libvips is behind Wolfi libvips 8.18.7" in capsys.readouterr().out


def test_gh_failure_warns_and_exits_zero(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "gh")
    code, _ = run(tmp_path, monkeypatch, "8.18.6", upsert=boom)
    assert code == 0 and "warning" in capsys.readouterr().err


def test_reads_index_dir(tmp_path, monkeypatch, capsys):
    idx = tmp_path / "idx"
    idx.mkdir()
    for arch in ("x86_64", "aarch64"):
        (idx / f"APKINDEX.{arch}").write_text("P:libvips\nV:8.19.1-r0\n\n")
    code, calls = run(tmp_path, monkeypatch, "8.18.7", "--index-dir", str(idx), "--dry-run")
    assert code == 0 and calls == [] and "Wolfi libvips 8.19.1" in capsys.readouterr().out
