import hashlib
import io
import re
from pathlib import Path

import pytest

from dltools import cli, lines
from dltools.lines import (
    OPENSSL_LEGACY_MELANGE,
    bump_melange,
    melange_version,
    openssl_legacy_behind,
)

ROOT = Path(__file__).parent.parent


def idx(**pkgs):
    return {"x86_64": dict(pkgs), "aarch64": dict(pkgs)}


def test_behind_follows_the_highest_released_3x_minor():
    wolfi = idx(**{"openssl-3.6-libcrypto": ["3.6.5-r7", "3.6.6-r0"], "openssl-4.0-libcrypto": ["4.0.3-r8"]})
    assert openssl_legacy_behind(wolfi, "3.6.5-r0") == "3.6.6"
    assert openssl_legacy_behind(wolfi, "3.6.6-r0") is None
    assert openssl_legacy_behind(wolfi, "3.6.10-r0") is None  # versions, not strings
    # A new minor counts too; pre-releases don't.
    minor = idx(**{"openssl-3.6-libcrypto": ["3.6.5-r7"], "openssl-3.7-libcrypto": ["3.7.0-r0", "3.7.1_rc1-r0"]})
    assert openssl_legacy_behind(minor, "3.6.5-r0") == "3.7.0"
    assert openssl_legacy_behind(idx(**{"openssl-3.6-libcrypto": ["3.6.5-r9"]}), "3.6.5-r0") is None  # epochs


def test_behind_needs_every_arch():
    one = {"x86_64": {"openssl-3.6-libcrypto": ["3.6.6-r0"]}, "aarch64": {"openssl-3.6-libcrypto": ["3.6.5-r7"]}}
    assert openssl_legacy_behind(one, "3.6.5-r0") is None
    assert openssl_legacy_behind({"x86_64": {}, "aarch64": {}}, "3.6.5-r0") is None


def test_bump_rewrites_version_epoch_and_sha_only():
    text = (ROOT / OPENSSL_LEGACY_MELANGE).read_text().replace("  epoch: 0", "  epoch: 2")
    out = bump_melange(text, "3.6.6", "a" * 64)
    assert re.search(r'(?m)^  version: "3\.6\.6"$', out) and re.search(r"(?m)^  epoch: 0$", out)
    assert f"expected-sha256: {'a' * 64}" in out
    changed = [(a, b) for a, b in zip(text.splitlines(), out.splitlines(), strict=True) if a != b]
    assert len(changed) == 3  # comments and everything else untouched
    with pytest.raises(ValueError):
        bump_melange("package:\n  name: x\n", "1", "a" * 64)


def test_repo_package_version_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+-r\d+", melange_version(ROOT / OPENSSL_LEGACY_MELANGE))


def test_release_sha256_is_checked_against_the_tarball(monkeypatch):
    tarball = b"openssl source"
    good = hashlib.sha256(tarball).hexdigest()

    def serve(published):
        def urlopen(url, timeout):
            return io.BytesIO(f"{published} *openssl-3.6.6.tar.gz\n".encode() if url.endswith(".sha256") else tarball)
        return urlopen

    monkeypatch.setattr(lines.urllib.request, "urlopen", serve(good))
    assert lines.openssl_release_sha256("3.6.6") == good
    monkeypatch.setattr(lines.urllib.request, "urlopen", serve("b" * 64))
    with pytest.raises(ValueError):
        lines.openssl_release_sha256("3.6.6")


def run(tmp_path, monkeypatch, wolfi_version, *extra):
    cfg = tmp_path / "distroless-openssl-legacy.yaml"
    cfg.write_text((ROOT / OPENSSL_LEGACY_MELANGE).read_text())
    monkeypatch.setattr(cli, "load_indexes", lambda _: idx(**{"openssl-3.6-libcrypto": [wolfi_version]}))
    monkeypatch.setattr(cli, "openssl_release_sha256", lambda v: "c" * 64)
    return cli.main(["openssl-legacy-check", "--melange", str(cfg), *extra]), cfg


def test_cli_prints_the_bump_and_applies_it(tmp_path, monkeypatch, capsys):
    code, cfg = run(tmp_path, monkeypatch, "3.6.6-r0")
    assert code == 0 and capsys.readouterr().out == "distroless-openssl-legacy 3.6.6\n"
    assert melange_version(cfg) == "3.6.5-r0"  # no --apply: nothing written
    code, cfg = run(tmp_path, monkeypatch, "3.6.6-r0", "--apply")
    assert code == 0 and melange_version(cfg) == "3.6.6-r0" and "c" * 64 in cfg.read_text()


def test_cli_up_to_date_prints_nothing_on_stdout(tmp_path, monkeypatch, capsys):
    code, _ = run(tmp_path, monkeypatch, "3.6.5-r7")
    out = capsys.readouterr()
    assert code == 0 and out.out == "" and "up to date" in out.err
