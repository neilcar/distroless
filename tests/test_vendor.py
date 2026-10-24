import hashlib
import json
import tarfile

import pytest

from dltools.vendor import appimage_offset, build_layer


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def launch_dir(tmp_path):
    for name in ("darktable", "tool"):
        (tmp_path / "launch" / name).mkdir(parents=True)
        (tmp_path / "launch" / name / "launch.json").write_text('{"exec": "x"}\n')
    return tmp_path / "launch"


@pytest.fixture
def launcher(tmp_path):
    p = tmp_path / "launcher"
    p.write_bytes(b"\x7fELF-launcher")
    return p


@pytest.fixture
def vendor(fake_appimage, tmp_path):
    binary = tmp_path / "tool-bin"
    binary.write_bytes(b"binary-tool")
    return {"vendor": [
        {"name": "darktable", "version": "1", "kind": "appimage", "prefix": "/opt/darktable",
         "files": {"x86_64": {"url": fake_appimage.as_uri(), "sha256": sha(fake_appimage)}},
         "launchers": ["darktable-cli"]},
        {"name": "tool", "version": "2", "kind": "binary", "prefix": "/opt/tool",
         "files": {"x86_64": {"url": binary.as_uri(), "sha256": sha(binary)}},
         "launchers": ["tool"]},
    ]}


def members(path):
    with tarfile.open(path) as tar:
        return tar.getmembers(), {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}


def test_appimage_offset_finds_squashfs(fake_appimage):
    offset = appimage_offset(fake_appimage)
    assert offset == int(fake_appimage.with_name("runtime-size").read_text())
    with open(fake_appimage, "rb") as f:
        f.seek(offset)
        assert f.read(4) == b"hsqs"


def test_appimage_offset_rejects_plain_elf(static_elf):
    with pytest.raises(ValueError):
        appimage_offset(static_elf)


def test_appimage_offset_rejects_non_elf(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"not an elf" * 20)
    with pytest.raises(ValueError):
        appimage_offset(p)


def test_build_layer_is_deterministic(vendor, tmp_path, launcher, launch_dir):
    a, b = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    build_layer(vendor, "x86_64", tmp_path / "cache", a, launcher, launch_dir)
    build_layer(vendor, "x86_64", tmp_path / "cache", b, launcher, launch_dir)
    assert a.read_bytes() == b.read_bytes()
    ms, _ = members(a)
    assert [m.name for m in ms] == sorted(m.name for m in ms)
    assert all(m.mtime == 0 and m.uid == 0 and m.gid == 0 for m in ms)
    assert all(not m.pax_headers for m in ms)
    assert "opt/darktable/usr/bin/tool" in {m.name for m in ms}
    by_name = {m.name: m for m in ms}
    assert by_name["opt/darktable/usr/bin/tool"].mode == 0o755
    assert by_name["opt/darktable/AppRun"].issym()
    assert by_name["opt/darktable/AppRun"].linkname == "usr/bin/tool"
    assert by_name["opt"].isdir()


def test_build_layer_returns_manifest(vendor, tmp_path, launcher, launch_dir):
    manifest = build_layer(vendor, "x86_64", tmp_path / "c", tmp_path / "o.tar.gz",
                           launcher, launch_dir)
    assert manifest["vendor"][0] == {
        "name": "darktable", "version": "1", "arch": "x86_64",
        "url": vendor["vendor"][0]["files"]["x86_64"]["url"],
        "sha256": vendor["vendor"][0]["files"]["x86_64"]["sha256"]}
    assert [m["name"] for m in manifest["vendor"]] == ["darktable", "tool"]


def test_build_layer_rejects_bad_sha256(vendor, tmp_path, launcher, launch_dir):
    vendor["vendor"][1]["files"]["x86_64"]["sha256"] = "0" * 64
    out = tmp_path / "out.tar.gz"
    with pytest.raises(ValueError, match="sha256 mismatch"):
        build_layer(vendor, "x86_64", tmp_path / "cache", out, launcher, launch_dir)
    assert not out.exists()


def test_build_layer_installs_launchers(vendor, tmp_path, launcher, launch_dir):
    out = tmp_path / "out.tar.gz"
    build_layer(vendor, "x86_64", tmp_path / "cache", out, launcher, launch_dir)
    ms, files = members(out)
    assert files["usr/bin/darktable-cli"] == launcher.read_bytes()
    assert files["usr/bin/tool"] == launcher.read_bytes()
    assert {m.name: m.mode for m in ms}["usr/bin/darktable-cli"] == 0o755
    assert json.loads(files["opt/darktable/launch.json"]) == {"exec": "x"}
    assert files["opt/tool/tool"] == b"binary-tool"
    assert {m.name: m.mode for m in ms}["opt/tool/tool"] == 0o755


def test_build_layer_installs_launcher_as_env(vendor, tmp_path, launcher, launch_dir):
    # The image has no coreutils; `#!/usr/bin/env perl` (exiftool) needs an env.
    out = tmp_path / "out.tar.gz"
    build_layer(vendor, "x86_64", tmp_path / "cache", out, launcher, launch_dir)
    ms, files = members(out)
    assert files["usr/bin/env"] == launcher.read_bytes()
    assert {m.name: m.mode for m in ms}["usr/bin/env"] == 0o755


def test_build_layer_requires_launch_recipe(vendor, tmp_path, launcher):
    with pytest.raises(FileNotFoundError, match="launch.json"):
        build_layer(vendor, "x86_64", tmp_path / "c", tmp_path / "o.tar.gz", launcher,
                    tmp_path / "no-such-dir")
    assert not (tmp_path / "o.tar.gz").exists()


def test_vendor_layer_cli(vendor, tmp_path, launcher, launch_dir):
    from dltools.cli import main
    (tmp_path / "vendor.json").write_text(json.dumps(vendor))
    assert main(["vendor-layer", "--vendor", str(tmp_path / "vendor.json"), "--arch", "x86_64",
                 "--launcher", str(launcher), "--cache", str(tmp_path / "c"),
                 "--out", str(tmp_path / "l.tar.gz"), "--manifest", str(tmp_path / "m.json"),
                 "--launch-dir", str(launch_dir)]) == 0
    assert json.loads((tmp_path / "m.json").read_text())["vendor"][0]["name"] == "darktable"
