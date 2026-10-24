import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "shebang_audit", Path(__file__).parent / "smoke" / "shebang_audit.py")
shebang_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shebang_audit)

PATH = "/usr/sbin:/sbin:/usr/bin:/bin"


def script(root: Path, rel: str, text: str, mode=0o755):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    p.chmod(mode)


def rootfs(tmp_path):
    root = tmp_path / "root"
    (root / "usr/bin").mkdir(parents=True)
    os.symlink("usr/bin", root / "bin")  # merged /usr, as in Wolfi
    script(root, "usr/bin/perl", "\x7fELF")
    script(root, "usr/bin/env", "\x7fELF")
    return root


def test_audit_passes_resolvable_interpreters(tmp_path):
    root = rootfs(tmp_path)
    script(root, "usr/bin/exiftool", "#!/usr/bin/env perl\n")
    script(root, "usr/bin/pod2man", "#!/bin/perl -w\n")  # through the /bin symlink
    script(root, "usr/share/doc.txt", "#!/nonexistent\n", mode=0o644)  # not executable
    assert shebang_audit.audit(str(root), PATH) == ([], [])


def test_audit_fails_missing_interpreter_and_env_target(tmp_path):
    root = rootfs(tmp_path)
    script(root, "usr/bin/a", "#!/usr/bin/python3\n")
    script(root, "usr/bin/b", "#!/usr/bin/env python3\n")
    script(root, "usr/bin/c", "#!/usr/bin/env -S perl -w\n")
    broken, _ = shebang_audit.audit(str(root), PATH)
    assert [b.split(":")[0] for b in broken] == ["/usr/bin/a", "/usr/bin/b", "/usr/bin/c"]
    assert "/usr/bin/python3 not in the image" in broken[0]
    assert "python3 not on PATH" in broken[1]


def test_audit_lists_shell_scripts(tmp_path):
    root = rootfs(tmp_path)
    script(root, "usr/bin/xzgrep", "#!/bin/sh\n")
    script(root, "opt/tool/AppRun", "#! /usr/bin/env bash\n")
    broken, shell = shebang_audit.audit(str(root), PATH)
    assert broken == []
    assert shell == ["/opt/tool/AppRun: /usr/bin/env bash", "/usr/bin/xzgrep: /bin/sh"]
