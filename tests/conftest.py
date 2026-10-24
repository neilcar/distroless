"""Session fixtures that need external tools; tests skip when the tool is absent."""

import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def need(tool: str) -> None:
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} not installed")


@pytest.fixture(scope="session")
def static_elf(tmp_path_factory) -> Path:
    """A small static linux/amd64 ELF built from tests/smoke/hello.go."""
    need("go")
    out = tmp_path_factory.mktemp("elf") / "hello"
    env = {"CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": "amd64",
           "HOME": str(out.parent), "GOCACHE": str(out.parent / "gocache"),
           "PATH": os.environ["PATH"]}
    subprocess.run(["go", "build", "-o", str(out), str(ROOT / "tests/smoke/hello.go")],
                   check=True, env=env)
    return out


@pytest.fixture(scope="session")
def fake_appimage(static_elf, tmp_path_factory) -> Path:
    """ELF runtime + squashfs of a small tree, laid out like an AppImage."""
    need("mksquashfs")
    need("unsquashfs")
    work = tmp_path_factory.mktemp("appimage")
    tree = work / "tree"
    (tree / "usr/bin").mkdir(parents=True)
    (tree / "usr/bin/tool").write_text("#!/bin/true\n")
    (tree / "usr/bin/tool").chmod(0o755)
    (tree / "data.txt").write_text("hello\n")
    (tree / "AppRun").symlink_to("usr/bin/tool")
    squash = work / "payload.squashfs"
    subprocess.run(["mksquashfs", str(tree), str(squash), "-noappend", "-all-root",
                    "-no-xattrs", "-quiet"], check=True, stdout=subprocess.DEVNULL)
    # Go puts its section header table early in the file; a real AppImage runtime has it at
    # the end. Append a header table there (3 null entries) and point the ELF header at it.
    elf = bytearray(static_elf.read_bytes())
    struct.pack_into("<Q", elf, 0x28, len(elf))
    struct.pack_into("<HH", elf, 0x3A, 64, 3)
    elf += bytes(64 * 3)
    image = work / "fake.AppImage"
    image.write_bytes(bytes(elf) + squash.read_bytes())
    image.with_name("runtime-size").write_text(str(len(elf)))
    return image


@pytest.fixture(scope="session")
def static_layout(tmp_path_factory) -> Path:
    """Two-arch OCI layout from `apko build` of the static image."""
    need("apko")
    work = tmp_path_factory.mktemp("apko")
    cfg = ROOT / "locks/static/latest/runtime.apko.yaml"
    if not cfg.exists():
        from dltools.cli import main
        main(["sync", "--locks", str(work / "locks"), "--state", str(work / "lines.json")])
        cfg = work / "locks/static/latest/runtime.apko.yaml"
    layout = work / "oci"
    layout.mkdir()
    subprocess.run(["apko", "build", "--sbom=false", "--arch", "x86_64,aarch64",
                    str(cfg), "static:test", f"{layout}/"],
                   check=True, capture_output=True)
    return layout
