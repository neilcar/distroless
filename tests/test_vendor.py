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


def test_build_layer_without_env_for_dev(vendor, tmp_path, launcher, launch_dir):
    # The dev variant keeps busybox's full env; only the runtime layer carries the launcher's.
    out = tmp_path / "dev.tar.gz"
    build_layer(vendor, "x86_64", tmp_path / "cache", out, launcher, launch_dir, env=False)
    _, files = members(out)
    assert "usr/bin/env" not in files
    assert files["usr/bin/darktable-cli"] == launcher.read_bytes()


def test_cli_vendor_layer_no_env(vendor, tmp_path, launcher, launch_dir):
    from dltools import cli
    vj = tmp_path / "vendor.json"
    vj.write_text(json.dumps(vendor))
    for flag, has_env in (([], True), (["--no-env"], False)):
        out = tmp_path / f"layer{len(flag)}.tar.gz"
        assert cli.main(["vendor-layer", "--vendor", str(vj), "--arch", "x86_64",
                         "--launcher", str(launcher), "--cache", str(tmp_path / "cache"),
                         "--out", str(out), "--manifest", str(tmp_path / "m.json"),
                         "--launch-dir", str(launch_dir), *flag]) == 0
        assert ("usr/bin/env" in members(out)[1]) == has_env


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


def make_wheel(path, extra=None):
    import zipfile
    files = {
        "pkg/__init__.py": b"VALUE = 1\n",
        "pkg-1.0.dist-info/METADATA": b"Name: pkg\nVersion: 1.0\n",
        "pkg-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
        "pkg-1.0.dist-info/RECORD": b"pkg/__init__.py,,\npkg-1.0.dist-info/RECORD,,\n",
        **(extra or {}),
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def wheel_vendor(wheel, files_key="any"):
    return {"vendor": [
        {"name": "pkg", "version": "1.0", "kind": "wheel",
         "prefix": "/usr/lib/python3.12/site-packages",
         "files": {files_key: {"url": wheel.as_uri(), "sha256": sha(wheel)}}},
    ]}


SITE = "usr/lib/python3.12/site-packages"


def test_wheel_installs_into_site_packages(tmp_path, launcher):
    wheel = make_wheel(tmp_path / "pkg-1.0-py3-none-any.whl")
    a, b = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    build_layer(wheel_vendor(wheel), "x86_64", tmp_path / "cache", a, launcher, env=False)
    build_layer(wheel_vendor(wheel), "x86_64", tmp_path / "cache", b, launcher, env=False)
    assert a.read_bytes() == b.read_bytes()
    ms, data = members(a)
    assert [m.name for m in ms] == sorted(m.name for m in ms)
    assert all(m.mtime == 0 and m.uid == 0 and m.gid == 0 for m in ms)
    # exactly the wheel's members (RECORD as shipped, no .pyc, no launchers) plus parent dirs
    assert set(data) == {f"{SITE}/pkg/__init__.py", f"{SITE}/pkg-1.0.dist-info/METADATA",
                         f"{SITE}/pkg-1.0.dist-info/WHEEL", f"{SITE}/pkg-1.0.dist-info/RECORD"}
    assert data[f"{SITE}/pkg/__init__.py"] == b"VALUE = 1\n"
    assert data[f"{SITE}/pkg-1.0.dist-info/RECORD"].startswith(b"pkg/__init__.py,,")
    assert {m.name for m in ms if m.isdir()} >= {SITE, f"{SITE}/pkg", f"{SITE}/pkg-1.0.dist-info"}
    assert not any(m.name.endswith(".pyc") or m.name.endswith("usr/bin") for m in ms)


def test_wheel_any_arch_key_used_for_both_arches(tmp_path, launcher):
    wheel = make_wheel(tmp_path / "pkg-1.0-py3-none-any.whl")
    for arch in ("x86_64", "aarch64"):
        out = tmp_path / f"{arch}.tar.gz"
        manifest = build_layer(wheel_vendor(wheel), arch, tmp_path / "cache", out, launcher, env=False)
        assert f"{SITE}/pkg/__init__.py" in members(out)[1]
        assert manifest["vendor"][0]["arch"] == arch


def test_wheel_rejects_platform_wheel(tmp_path, launcher):
    wheel = make_wheel(tmp_path / "pkg-1.0-cp312-cp312-manylinux_2_17_x86_64.whl")
    out = tmp_path / "out.tar.gz"
    with pytest.raises(ValueError, match="pure-Python"):
        build_layer(wheel_vendor(wheel), "x86_64", tmp_path / "cache", out, launcher, env=False)
    assert not out.exists()


def test_wheel_rejects_bad_sha256(tmp_path, launcher):
    wheel = make_wheel(tmp_path / "pkg-1.0-py3-none-any.whl")
    vendor = wheel_vendor(wheel)
    vendor["vendor"][0]["files"]["any"]["sha256"] = "0" * 64
    out = tmp_path / "out.tar.gz"
    with pytest.raises(ValueError, match="sha256"):
        build_layer(vendor, "x86_64", tmp_path / "cache", out, launcher, env=False)
    assert not out.exists()


def test_wheel_rejects_path_escaping_member(tmp_path, launcher):
    wheel = make_wheel(tmp_path / "pkg-1.0-py3-none-any.whl", {"../evil.py": b"x"})
    out = tmp_path / "out.tar.gz"
    with pytest.raises(ValueError, match="unsafe"):
        build_layer(wheel_vendor(wheel), "x86_64", tmp_path / "cache", out, launcher, env=False)
    assert not out.exists()


@pytest.mark.parametrize("name", ["pkg-1.0-py3-none-any.whl", "pkg-1.0-py2.py3-none-any.whl"])
def test_wheel_accepts_pure_tags(tmp_path, launcher, name):
    wheel = make_wheel(tmp_path / name)
    out = tmp_path / "out.tar.gz"
    build_layer(wheel_vendor(wheel), "x86_64", tmp_path / "cache", out, launcher, env=False)
    assert f"{SITE}/pkg/__init__.py" in members(out)[1]


@pytest.mark.parametrize("name", [
    "pkg-1.0-cp312-cp312-manylinux_2_17_x86_64.whl",
    "pkg-1.0-py2-none-any.whl",        # no py3 tag
    "pkg-1.0-py3-abi3-any.whl",        # an ABI
    "pkg-1.0-py3-none-linux_x86_64.whl",  # a platform
    "pkg-1.0-cp312-none-any.whl",      # CPython-only
])
def test_wheel_rejects_non_pure_tags(tmp_path, launcher, name):
    wheel = make_wheel(tmp_path / name)
    with pytest.raises(ValueError, match="pure-Python"):
        build_layer(wheel_vendor(wheel), "x86_64", tmp_path / "cache", tmp_path / "o.tar.gz",
                    launcher, env=False)


def test_tar_binary_installs_one_member(tmp_path, launcher, launch_dir):
    """kind tar-binary: one executable taken out of a pinned release tarball (e.g. fpcalc)."""
    src = tmp_path / "fpcalc-src"
    src.mkdir()
    (src / "fpcalc").write_bytes(b"\x7fELF-fpcalc")
    (src / "LICENSE.md").write_text("license")
    tgz = tmp_path / "chromaprint-fpcalc.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(src / "fpcalc", arcname="chromaprint-fpcalc-1.6.2-linux-x86_64/fpcalc")
        tar.add(src / "LICENSE.md", arcname="chromaprint-fpcalc-1.6.2-linux-x86_64/LICENSE.md")
    vendor = {"vendor": [{"name": "fpcalc", "version": "1.6.2", "kind": "tar-binary", "prefix": "/usr/bin",
                          "files": {"x86_64": {"url": tgz.as_uri(), "sha256": sha(tgz),
                                               "member": "chromaprint-fpcalc-1.6.2-linux-x86_64/fpcalc"}}}]}
    out = tmp_path / "layer.tar.gz"
    build_layer(vendor, "x86_64", tmp_path / "cache", out, launcher, launch_dir)
    ms, data = members(out)
    by_name = {m.name: m for m in ms}
    assert data["usr/bin/fpcalc"] == b"\x7fELF-fpcalc" and by_name["usr/bin/fpcalc"].mode == 0o755
    assert not any("LICENSE" in n for n in by_name)


def test_tar_binary_missing_member_fails(tmp_path, launcher, launch_dir):
    tgz = tmp_path / "empty.tar.gz"
    with tarfile.open(tgz, "w:gz"):
        pass
    vendor = {"vendor": [{"name": "fpcalc", "version": "1", "kind": "tar-binary", "prefix": "/usr/bin",
                          "files": {"x86_64": {"url": tgz.as_uri(), "sha256": sha(tgz), "member": "x/fpcalc"}}}]}
    with pytest.raises(KeyError):
        build_layer(vendor, "x86_64", tmp_path / "cache", tmp_path / "l.tar.gz", launcher, launch_dir)
