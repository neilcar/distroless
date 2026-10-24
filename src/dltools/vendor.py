"""Build the vendor layer: upstream files that are not Wolfi packages, as one deterministic tarball."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

SQUASHFS_MAGIC = b"hsqs"
DEFAULT_LAUNCH_DIR = Path(__file__).resolve().parents[2] / "vendor"


def appimage_offset(path: Path) -> int:
    """Where the squashfs payload starts: the end of the ELF runtime (section header table)."""
    with open(path, "rb") as f:
        header = f.read(64)
        if len(header) < 64 or header[:4] != b"\x7fELF":
            raise ValueError(f"{path}: not an ELF file")
        if header[4] != 2 or header[5] != 1:
            raise ValueError(f"{path}: only 64-bit little-endian ELF is supported")
        shoff, = struct.unpack_from("<Q", header, 0x28)
        shentsize, shnum = struct.unpack_from("<HH", header, 0x3A)
        offset = shoff + shentsize * shnum
        f.seek(offset)
        if f.read(4) != SQUASHFS_MAGIC:
            raise ValueError(f"{path}: no squashfs image at offset {offset}")
    return offset


def fetch(url: str, sha256: str, cache_dir: Path) -> Path:
    """The file at `url` in the cache, verified against `sha256` (downloaded if missing)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{sha256}-{PurePosixPath(url).name}"

    def sha_of(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    if dest.exists() and sha_of(dest) == sha256:
        return dest
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        actual = sha_of(tmp)
        if actual != sha256:
            raise ValueError(f"sha256 mismatch for {url}: expected {sha256}, got {actual}")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _extract_appimage(appimage: Path, dest: Path) -> None:
    subprocess.run(
        ["unsquashfs", "-no-xattrs", "-o", str(appimage_offset(appimage)),
         "-d", str(dest), "-f", str(appimage)],
        check=True, stdout=subprocess.DEVNULL,
    )
    # unsquashfs keeps squashfs modes; make sure we can walk and remove everything.
    for root, dirs, _files in os.walk(dest):
        os.chmod(root, os.stat(root).st_mode | stat.S_IRWXU)


class _Layer:
    """Staged files for the tarball: rel path -> (kind, mode, source)."""

    def __init__(self) -> None:
        self.entries: dict[str, tuple[str, int, object]] = {}

    def _parents(self, rel: str) -> None:
        for parent in list(PurePosixPath(rel).parents)[:-1]:
            self.entries.setdefault(str(parent), ("dir", 0o755, None))

    def add(self, rel: str, kind: str, mode: int, source: object = None) -> None:
        rel = rel.strip("/")
        self._parents(rel)
        self.entries[rel] = (kind, mode, source)

    def add_tree(self, root: Path, prefix: str) -> None:
        self.add(prefix, "dir", 0o755)
        for dirpath, dirnames, filenames in os.walk(root):
            for name in dirnames + filenames:
                full = Path(dirpath) / name
                rel = f"{prefix.strip('/')}/{full.relative_to(root).as_posix()}"
                st = full.lstat()
                if stat.S_ISLNK(st.st_mode):
                    self.add(rel, "symlink", 0o777, os.readlink(full))
                elif stat.S_ISDIR(st.st_mode):
                    self.add(rel, "dir", 0o755)
                elif stat.S_ISREG(st.st_mode):
                    self.add(rel, "file", 0o755 if st.st_mode & 0o111 else 0o644, full)

    def write(self, out: Path) -> None:
        buf = io.BytesIO()
        with (gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz,
              tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar):
            for rel in sorted(self.entries):
                kind, mode, source = self.entries[rel]
                info = tarfile.TarInfo(rel)
                info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                info.mode = mode
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    tar.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = str(source)
                    tar.addfile(info)
                else:
                    info.size = Path(source).stat().st_size
                    with open(source, "rb") as f:
                        tar.addfile(info, f)
        tmp = out.with_name(out.name + ".part")
        tmp.write_bytes(buf.getvalue())
        tmp.replace(out)


def build_layer(vendor: dict, arch: str, cache_dir: Path, out: Path, launcher_bin: Path,
                launch_dir: Path = DEFAULT_LAUNCH_DIR, env: bool = True) -> dict:
    """Write the vendor layer for `arch` to `out` (.tar.gz); returns what went into it.

    With `env`, the launcher is also installed as /usr/bin/env (for images without
    coreutils); a variant with busybox keeps busybox's full env instead."""
    cache_dir, out = Path(cache_dir), Path(out)
    entries = vendor["vendor"]
    # Download and verify everything before unpacking any of it.
    fetched = [(e, fetch(e["files"][arch]["url"], e["files"][arch]["sha256"], cache_dir))
               for e in entries]

    layer = _Layer()
    manifest = []
    with tempfile.TemporaryDirectory() as tmp:
        for entry, path in fetched:
            name, prefix, launchers = entry["name"], entry["prefix"], entry.get("launchers", [])
            if entry["kind"] == "appimage":
                dest = Path(tmp) / name
                _extract_appimage(path, dest)
                layer.add_tree(dest, prefix)
            elif entry["kind"] == "binary":
                layer.add(prefix, "dir", 0o755)
                layer.add(f"{prefix}/{launchers[0] if launchers else name}", "file", 0o755, path)
            else:
                raise ValueError(f"{name}: unknown kind {entry['kind']!r}")
            if launchers:
                recipe = Path(launch_dir) / name / "launch.json"
                if not recipe.is_file():
                    raise FileNotFoundError(f"{name} lists launchers but {recipe} does not exist")
                layer.add(f"{prefix}/launch.json", "file", 0o644, recipe)
                for launcher in launchers:
                    layer.add(f"usr/bin/{launcher}", "file", 0o755, Path(launcher_bin))
            f = entry["files"][arch]
            manifest.append({"name": name, "version": entry["version"], "arch": arch,
                             "url": f["url"], "sha256": f["sha256"]})
        # The launcher is also env(1): the runtime image has no coreutils, and scripts such
        # as Wolfi's exiftool start with `#!/usr/bin/env perl`.
        if env:
            layer.add("usr/bin/env", "file", 0o755, Path(launcher_bin))
        out.parent.mkdir(parents=True, exist_ok=True)
        layer.write(out)
    return {"vendor": manifest}
