"""Check that every script in an exported image root can find its interpreter.

Usage: python3 -I shebang_audit.py <rootfs dir> <image PATH>

For each regular executable file starting with `#!`, the interpreter must exist (and be
executable) inside the root. `#!/usr/bin/env X` also needs X on the image's PATH. Scripts
for /bin/sh or bash (directly or through env) are listed, not failed: the runtime image
has no shell by design. Exits 1 if any script is broken.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import PurePosixPath

SHELLS = {"/bin/sh", "/bin/bash", "/usr/bin/bash"}
SHELL_NAMES = {"sh", "bash"}  # `#!/usr/bin/env bash` is a shell script too


def resolve(root: str, path: str, depth: int = 0) -> str | None:
    """`path` (absolute, inside the image) as a host path, following symlinks within root."""
    if depth > 40:
        return None
    parts = PurePosixPath(path).parts[1:]
    cur = "/"
    for i, part in enumerate(parts):
        nxt = str(PurePosixPath(cur) / part)
        host = os.path.join(root, nxt.lstrip("/"))
        try:
            st = os.lstat(host)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(st.st_mode):
            target = os.readlink(host)
            base = target if target.startswith("/") else str(PurePosixPath(cur) / target)
            rest = "/".join(parts[i + 1:])
            return resolve(root, os.path.normpath(base + ("/" + rest if rest else "")), depth + 1)
        cur = nxt
    return os.path.join(root, cur.lstrip("/"))


def executable(root: str, path: str) -> bool:
    host = resolve(root, path)
    if host is None:
        return False
    st = os.stat(host)
    return stat.S_ISREG(st.st_mode) and bool(st.st_mode & 0o111)


def audit(root: str, image_path: str) -> tuple[list[str], list[str]]:
    broken, shell = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            host = os.path.join(dirpath, name)
            st = os.lstat(host)
            if not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111:
                continue
            try:
                with open(host, "rb") as f:
                    head = f.readline(512)
            except OSError as e:
                broken.append(f"/{os.path.relpath(host, root)}: unreadable on the runner ({e})")
                continue
            if not head.startswith(b"#!"):
                continue
            rel = "/" + os.path.relpath(host, root)
            words = head[2:].decode("utf-8", "replace").split()
            if not words:
                broken.append(f"{rel}: empty #! line")
                continue
            interp = words[0]
            if interp in SHELLS:
                shell.append(f"{rel}: {interp}")
            elif not executable(root, interp):
                broken.append(f"{rel}: interpreter {interp} not in the image")
            elif PurePosixPath(interp).name == "env":
                prog = words[1] if len(words) > 1 else ""
                if prog in SHELL_NAMES:
                    shell.append(f"{rel}: {interp} {prog}")
                elif not prog or prog.startswith("-"):
                    broken.append(f"{rel}: {interp} {prog!r}: env takes no options here")
                elif not any(executable(root, f"{d}/{prog}") for d in image_path.split(":") if d):
                    broken.append(f"{rel}: {interp} {prog}: {prog} not on PATH ({image_path})")
    return broken, shell


def main() -> int:
    root, image_path = sys.argv[1], sys.argv[2]
    broken, shell = audit(root, image_path)
    for s in shell:
        print(f"shell script (no shell in the image, not used): {s}")
    for b in broken:
        print(f"BROKEN SHEBANG: {b}", file=sys.stderr)
    print(f"shebang audit: {len(broken)} broken, {len(shell)} shell scripts listed")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
