#!/usr/bin/env bash
# Smoke-test a locally loaded image. Usage: test_images.sh <image-ref> <image> <variant>
set -euo pipefail
ref=$1 image=$2 variant=$3
fail() { echo "SMOKE FAIL ($image/$variant): $*" >&2; exit 1; }

user=$(docker inspect --format '{{.Config.User}}' "$ref")
if [[ "$image" == "photoprism-base" || "$image" == "debug" || "$image" == "rust" ]]; then  # root (photoprism-base: owner's decision; debug: reaches a target's files; rust: job containers write the workspace)
  [[ "$user" == "0" || "$user" == "root" || "$user" == "0:0" ]] || fail "user is '$user'"
elif [[ "$image" == "stash-base" ]]; then  # Stash's pod runs as 1000:1000
  [[ "$user" == "1000" || "$user" == "stash" || "$user" == "1000:1000" ]] || fail "user is '$user'"
elif [[ "$image" == "sabnzbd-base" ]]; then  # SABnzbd's pod runs as 1000:1000
  [[ "$user" == "1000" || "$user" == "sabnzbd" || "$user" == "1000:1000" ]] || fail "user is '$user'"
elif [[ "$image" == "servarr-base" ]]; then  # the Servarr pods run as 1000:1000
  [[ "$user" == "1000" || "$user" == "servarr" || "$user" == "1000:1000" ]] || fail "user is '$user'"
elif [[ "$image" == "python-ssh" ]]; then  # the feral-janitor Job runs as 1000:1000
  [[ "$user" == "1000" || "$user" == "janitor" || "$user" == "1000:1000" ]] || fail "user is '$user'"
elif [[ "$image" == "valkey" ]]; then  # photoprism-index-redis's pod runs as 999:999
  [[ "$user" == "999" || "$user" == "valkey" || "$user" == "999:999" ]] || fail "user is '$user'"
elif [[ "$image" == "beets-base" ]]; then  # beets' pod runs as 1000:1000
  [[ "$user" == "1000" || "$user" == "beets" || "$user" == "1000:1000" ]] || fail "user is '$user'"
else
  [[ "$user" == "65532" || "$user" == "nonroot" || "$user" == "65532:65532" ]] || fail "user is '$user'"
fi

has_file() { docker run --rm --entrypoint "" "$ref" "$@" >/dev/null 2>&1; }
tool() { docker run --rm --entrypoint "$1" "$ref" "${@:2}"; }
# Every script must find its interpreter (no shell in the image, so look from outside).
shebang_audit() {
  local root cid image_path
  root=$(mktemp -d)
  cid=$(docker create --entrypoint /none "$ref")
  docker export "$cid" | tar -x -C "$root" --exclude='dev' --exclude='dev/*'
  docker rm "$cid" >/dev/null
  image_path=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$ref" \
    | sed -n 's/^PATH=//p')
  python3 -I "$(dirname "$0")/shebang_audit.py" "$root" "${image_path:-/usr/sbin:/sbin:/usr/bin:/bin}" \
    || fail "scripts whose interpreter is missing (see above)"
  rm -rf "$root"
}
if [[ "$variant" == "runtime" ]]; then
  ! docker run --rm --entrypoint /bin/sh "$ref" -c true >/dev/null 2>&1 || fail "runtime image has a shell"
  ! docker run --rm --entrypoint /sbin/apk "$ref" --version >/dev/null 2>&1 || fail "runtime image has apk"
fi

case "$image" in
  python)
    docker run --rm "$ref" -c 'import ssl, sqlite3, zoneinfo, json; zoneinfo.ZoneInfo("Europe/London"); print(ssl.OPENSSL_VERSION)' \
      || fail "python stdlib check"
    if [[ "$variant" == "dev" ]]; then
      docker run --rm --entrypoint /bin/sh "$ref" -c 'uv --version && pip --version' || fail "dev tools"
    fi
    ;;
  nginx)
    cid=$(docker run -d -p 18080:8080 "$ref")
    trap 'docker rm -f "$cid" >/dev/null' EXIT
    for _ in $(seq 1 20); do
      code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/ || true)
      [[ "$code" == "200" ]] && break
      sleep 0.5
    done
    [[ "$code" == "200" ]] || { docker logs "$cid" >&2; fail "nginx returned '$code' on 8080"; }
    if docker logs "$cid" 2>&1 | grep -E '\[(alert|emerg|crit)\]'; then fail "nginx logged alerts"; fi
    ;;
  static)
    dir=$(mktemp -d)
    (cd "$(dirname "$0")" && CGO_ENABLED=0 GOOS=linux go build -o "$dir/hello" hello.go)
    printf 'FROM %s\nCOPY hello /hello\nENTRYPOINT ["/hello"]\n' "$ref" > "$dir/Dockerfile"
    docker build -q -t smoke-static "$dir" >/dev/null
    [[ "$(docker run --rm smoke-static)" == "ok" ]] || fail "static binary"
    ;;
  photoprism-base)
    for cmd in "ffmpeg -version" "exiftool -ver" "heif-dec --version" "magick -version" \
               "vips --version" "djxl --version" "rsvg-convert --version" "mariadb --version" \
               "mariadb-dump --version" "yt-dlp --version"; do
      # shellcheck disable=SC2086  # each entry is "tool args"
      tool $cmd >/dev/null || fail "$cmd"
    done
    # distroless-libvips is built with lcms2: colour profiles can be converted.
    out=$(tool vips -l) || fail "vips -l"
    grep -q 'icc_transform' <<<"$out" || fail "libvips has no icc_transform"
    out=$(tool vips --vips-config) || fail "vips --vips-config"
    grep -q 'ICC profile support with lcms2: true' <<<"$out" || fail "libvips is built without lcms2"
    [[ "$variant" == "runtime" ]] && shebang_audit
    out=$(tool darktable-cli --version) || fail "darktable-cli --version"
    grep -q '5\.6\.2' <<<"$out" || fail "darktable-cli is not 5.6.2: $out"
    out=$(tool rawtherapee-cli -v || true)  # upstream prints the version, then exits 255
    grep -q '5\.13' <<<"$out" || fail "rawtherapee-cli is not 5.13: $out"
    if [[ "$variant" == "runtime" ]]; then
      # /usr/bin/env is the launcher's minimal env: no options.
      out=$(tool /usr/bin/env -u FOO /usr/bin/perl -e 1 2>&1) && fail "runtime env accepted an option"
      grep -q 'env: options are not supported: -u' <<<"$out" || fail "runtime env is not the launcher: $out"
    else
      # dev keeps busybox's full env.
      tool /usr/bin/env -u FOO /bin/true || fail "dev env -u FOO /bin/true"
      tool /usr/bin/env -i /bin/true || fail "dev env -i /bin/true"
    fi
    if [[ "$variant" == "dev" ]]; then
      for cmd in "go version" "node --version" "npm --version" "make --version" "bash --version" \
                 "rsync --version" "wget --version"; do
        # shellcheck disable=SC2086
        tool $cmd >/dev/null || fail "$cmd"
      done
      # PhotoPrism's `make install` needs GNU tar and coreutils, not busybox's applets.
      out=$(tool tar --version) || fail "tar --version"
      grep -q 'GNU tar' <<<"$out" || fail "tar is not GNU tar: $out"
      out=$(tool ls --version) || fail "ls --version"
      grep -q 'GNU coreutils' <<<"$out" || fail "ls is not GNU coreutils: $out"
      # The frontend build needs Node >= 24.15.
      out=$(tool node -p 'const [a, b] = process.versions.node.split(".").map(Number); a > 24 || (a == 24 && b >= 15)') \
        || fail "node version check"
      [[ "$out" == "true" ]] || fail "node is older than 24.15: $(tool node --version)"
    fi
    ;;
  stash-base)
    # Parity with today's Stash image: what live transcoding and generation use.
    out=$(tool ffmpeg -hide_banner -encoders) || fail "ffmpeg -encoders"
    for enc in libx264 libx265 libvpx libvpx-vp9 libopus aac libwebp; do
      grep -qE "^ [A-Z.]{6} $enc " <<<"$out" || fail "ffmpeg has no $enc encoder"
    done
    out=$(tool ffmpeg -hide_banner -decoders) || fail "ffmpeg -decoders"
    for dec in hevc h264 vp9 av1 mpeg4 wmv2; do
      grep -qE "^ [A-Z.]{6} $dec " <<<"$out" || fail "ffmpeg has no $dec decoder"
    done
    tool ffprobe -version >/dev/null || fail "ffprobe -version"
    out=$(tool vips -l) || fail "vips -l"
    grep -q 'icc_transform' <<<"$out" || fail "libvips has no icc_transform"
    tool vipsthumbnail --version >/dev/null || fail "vipsthumbnail --version"
    # Libraries the enabled plugins and the Python scrapers import, under both names.
    imports='import requests, requests_toolbelt, lxml.html, bs4, cloudscraper, mechanicalsoup
import stashapi.stashapp, stashapi.stashbox, stashapi.log
import apscheduler.schedulers.background, tzlocal, dateparser, regex, dateutil, pytz
assert dateparser.parse("2024-03-05").year == 2024
print("imports ok")'
    for py in python python3; do  # TZ as the chart sets it (tzlocal warns without one)
      out=$(docker run --rm -e TZ=Etc/UTC --entrypoint "$py" "$ref" -c "$imports" 2>&1) \
        || fail "$py imports: $out"
      [[ "$out" == "imports ok" ]] || fail "$py imports printed: $out"
    done
    tool python -m pip --version >/dev/null || fail "python -m pip --version"
    # The EmbeddedMetadata scraper: PyExifTool runs exiftool (`#!/usr/bin/env perl`).
    tool exiftool -ver >/dev/null || fail "exiftool -ver as uid $user"
    # PythonDepManager and py_common pip-install packages at runtime as uid 1000 (no compiler);
    # EmbeddedMetadata's pyexiv2 is a manylinux wheel. This only proves runtime pip can fetch
    # and load a glibc wheel, so the versions are pinned (a new upstream release must not fail
    # the base build). Needs PyPI: skipped when offline.
    if curl -s -o /dev/null --max-time 10 https://pypi.org/simple/pip/; then
      docker run --rm -e HOME=/tmp --entrypoint python3 "$ref" -m pip download --no-input --quiet \
        --disable-pip-version-check pyexiv2==2.16.0 --no-deps --only-binary=:all: -d /tmp/x \
        || fail "pip found no pyexiv2 wheel for this platform"
      # ... and the scraper's whole path works: pyexiv2 loads, PyExifTool drives exiftool.
      out=$(docker run --rm -e HOME=/tmp -e TZ=Etc/UTC --entrypoint python3 "$ref" -c '
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-input", "--no-deps",
                "--disable-pip-version-check", "--only-binary=:all:", "--target", "/tmp/d",
                "pyexiv2==2.16.0", "pyexiftool==0.5.6"], check=True)
sys.path.insert(0, "/tmp/d")
import pyexiv2, exiftool
with exiftool.ExifToolHelper() as et:
    print("embedded ok", bool(et.version))' 2>&1) || fail "EmbeddedMetadata libraries: $out"
      [[ "$out" == "embedded ok True" ]] || fail "EmbeddedMetadata libraries printed: $out"
    else
      echo "smoke note ($image/$variant): PyPI unreachable, skipped the runtime pip checks"
    fi
    # Plugins start with `#!/usr/bin/env python3` (the runtime env is the launcher).
    dir=$(mktemp -d)
    printf '#!/usr/bin/env python3\nimport sys; print("env ok", sys.version_info[:2])\n' > "$dir/hello.py"
    chmod 0755 "$dir" "$dir/hello.py"
    out=$(docker run --rm -v "$dir:/smoke:ro" --entrypoint /smoke/hello.py "$ref") || fail "env python3 script"
    [[ "$out" == "env ok (3, 12)" ]] || fail "env python3 script printed '$out'"
    rm -rf "$dir"
    if [[ "$variant" == "runtime" ]]; then
      shebang_audit
      out=$(tool /usr/bin/env -u FOO /usr/bin/python3 -c 1 2>&1) && fail "runtime env accepted an option"
      grep -q 'env: options are not supported: -u' <<<"$out" || fail "runtime env is not the launcher: $out"
    else
      # Stash builds from source: Go >= 1.24.3 (go.mod), Node >= 24.
      out=$(tool go env GOVERSION) || fail "go env GOVERSION"
      printf '%s\n' go1.24.3 "$out" | sort -V -C || fail "go is older than 1.24.3: $out"
      out=$(tool node -p 'Number(process.versions.node.split(".")[0]) >= 24') || fail "node version check"
      [[ "$out" == "true" ]] || fail "node is older than 24: $(tool node --version)"
      for cmd in "make --version" "gcc --version" "npm --version" "git --version"; do
        # shellcheck disable=SC2086
        tool $cmd >/dev/null || fail "$cmd"
      done
    fi
    ;;
  beets-base)
    # beets' Python: 3.12 as /usr/bin/python3 (the auto-import entry points' shebang), with the stdlib
    # modules beets and the entry points use.
    out=$(tool /usr/bin/python3 -c '
import sys, ssl, sqlite3, fcntl, zoneinfo, json, subprocess
assert sys.version_info[:2] == (3, 12), sys.version
zoneinfo.ZoneInfo("Europe/London")
print("python ok", ssl.OPENSSL_VERSION)' 2>&1) || fail "python3 check: $out"
    [[ "$out" == "python ok OpenSSL "* ]] || fail "python3 check printed: $out"
    out=$(tool tini --version 2>&1) || fail "tini --version: $out"
    grep -q '^tini version' <<<"$out" || fail "tini printed: $out"
    out=$(tool fpcalc -version 2>&1) || fail "fpcalc -version: $out"
    grep -q '^fpcalc version 1\.6\.2' <<<"$out" || fail "fpcalc printed: $out"
    for t in ffmpeg ffprobe; do
      out=$(tool $t -version 2>&1) || fail "$t -version: $out"
      grep -q "^$t version" <<<"$out" || fail "$t printed: $(head -1 <<<"$out")"
    done
    out=$(tool metaflac --version 2>&1) || fail "metaflac --version: $out"
    grep -q '^metaflac' <<<"$out" || fail "metaflac printed: $out"
    out=$(tool magick -version 2>&1) || fail "magick -version: $out"
    grep -q 'ImageMagick 7' <<<"$out" || fail "magick printed: $(head -1 <<<"$out")"
    # A round trip through ffmpeg and magick as uid 1000 in /tmp (what convert/fetchart do).
    out=$(tool /usr/bin/python3 -c '
import os, subprocess
os.chdir("/tmp")
subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", "s.flac"], check=True)
subprocess.run(["magick", "-size", "64x64", "xc:red", "a.png"], check=True)
subprocess.run(["magick", "a.png", "-resize", "32x32", "b.jpg"], check=True)
print(os.path.getsize("s.flac") > 0 and os.path.getsize("b.jpg") > 0)' 2>&1) || fail "media round trip: $out"
    [[ "$out" == "True" ]] || fail "media round trip printed: $out"
    out=$(tool /usr/bin/python3 -c 'import os; s = os.stat("/config"); print(s.st_uid, s.st_gid, os.path.expanduser("~"))') \
      || fail "stat /config"
    [[ "$out" == "1000 1000 /config" ]] || fail "/config: $out"
    if [[ "$variant" == "runtime" ]]; then
      shebang_audit
      has_file /bin/sh && fail "/bin/sh present in the runtime"
    else
      out=$(tool python3 -m pip --version 2>&1) || fail "pip: $out"
      out=$(tool uv --version 2>&1) || fail "uv: $out"
    fi
    ;;
  servarr-base)
    # Lidarr's fingerprinter (chromaprint's static release build).
    out=$(tool fpcalc -version 2>&1) || fail "fpcalc -version: $out"
    grep -q '^fpcalc version 1\.6\.2' <<<"$out" || fail "fpcalc printed: $out"
    # What the .NET apps load, looked for from outside (no shell or Python in the image).
    root=$(mktemp -d)
    cid=$(docker create --entrypoint /none "$ref")
    docker export "$cid" | tar -x -C "$root" --exclude='dev' --exclude='dev/*'
    docker rm "$cid" >/dev/null
    for f in usr/lib/libicuuc.so.79 usr/lib/libicui18n.so.79 usr/lib/libicudata.so.79 usr/lib/libssl.so.3 \
             usr/lib/libcrypto.so.3 usr/lib/libz.so.1 usr/lib/libsqlite3.so.0 usr/lib/libstdc++.so.6 \
             usr/lib/libgcc_s.so.1 usr/share/zoneinfo/Europe/London etc/ssl/certs/ca-certificates.crt; do
      [[ -e "$root/$f" ]] || fail "missing /$f"
    done
    rm -rf "$root"
    # Ownership from the tar listing (an unprivileged extract would chown to the runner).
    cid=$(docker create --entrypoint /none "$ref")
    owner=$(docker export "$cid" | tar -tv --numeric-owner | awk '$NF == "config/" {print $2}')
    docker rm "$cid" >/dev/null
    [[ "$owner" == "1000/1000" ]] || fail "/config owner is '$owner'"
    ;;
  debug)
    # The toolbox: every tool is there and runs (bash is the entrypoint).
    docker run --rm "$ref" -c '
      set -e
      for t in ls find grep sed awk ps less file tar gzip nsenter curl openssl jq yq sqlite3 dig nc ss ip \
               tcpdump strace lsof; do
        command -v "$t" >/dev/null || { echo "missing $t"; exit 1; }
      done
      curl --version >/dev/null; jq --version >/dev/null; yq --version >/dev/null
      dig -v >/dev/null 2>&1; tcpdump --version >/dev/null; strace -V >/dev/null; nsenter --version >/dev/null
      echo "{\"a\":1}" | jq -e ".a == 1" >/dev/null
      [ "$(sqlite3 :memory: "select 1")" = 1 ]
    ' || fail "debug tools"
    ;;
  ci-tools)
    # hey-furby's smoke test: curl as the entrypoint (as curlimages/curl), and busybox's chown
    # as root on a volume (`--entrypoint chown -u 0`).
    out=$(docker run --rm "$ref" --version) || fail "curl --version: $out"
    grep -q '^curl 8' <<<"$out" || fail "curl --version printed: $out"
    grep -q 'https' <<<"$out" || fail "curl has no https: $out"
    vol=ci-tools-smoke-$$
    docker volume create "$vol" >/dev/null
    docker run --rm -u 0 -v "$vol":/data --entrypoint chown "$ref" 1000:1000 /data \
      || { docker volume rm "$vol" >/dev/null; fail "chown"; }
    owner=$(docker run --rm -v "$vol":/data --entrypoint stat "$ref" -c %u:%g /data)
    docker volume rm "$vol" >/dev/null
    [[ "$owner" == "1000:1000" ]] || fail "chown left /data as $owner"
    for t in sh chown chmod stat; do
      tool which "$t" >/dev/null || fail "missing $t"
    done
    ;;
  valkey)
    # photoprism-k8s's CI service: started with no arguments, it answers on a published port.
    cid=$(docker run -d -p 16379:6379 "$ref")
    trap 'docker rm -f "$cid" >/dev/null' EXIT
    for _ in $(seq 1 20); do
      out=$(docker run --rm --network container:"$cid" --entrypoint valkey-cli "$ref" ping 2>&1 || true)
      [[ "$out" == "PONG" ]] && break
      sleep 0.5
    done
    [[ "$out" == "PONG" ]] || { docker logs "$cid" >&2; fail "valkey-cli ping: $out"; }
    # From outside the container (protected mode is off), and writes persist to /data.
    exec 3<>/dev/tcp/127.0.0.1/16379 || fail "no connection on the published port"
    printf 'SET k v\r\nSAVE\r\n' >&3
    read -r -t 5 r1 <&3; read -r -t 5 r2 <&3; exec 3<&-
    [[ "$r1" == +OK* && "$r2" == +OK* ]] || fail "SET/SAVE over the published port: $r1 $r2"
    ;;
  rust)
    # ollama-orchestrator's CI job and build stage: cargo fmt/clippy/test and a crate with C (cc).
    docker run --rm "$ref" -c '
      set -e
      cargo --version; rustc --version; cargo clippy --version; cargo fmt --version; git --version
      cd /tmp && cargo new -q hello && cd hello
      printf "fn main() {\n    println!(\"hello\");\n}\n" > src/main.rs
      cargo fmt --check
      cargo clippy -q -- -D warnings
      cargo build -q --release
      [ "$(./target/release/hello)" = hello ]
      printf "int seven(void) { return 7; }\n" > /tmp/seven.c && cc -c /tmp/seven.c -o /tmp/seven.o
    ' || fail "rust toolchain"
    ;;
  cc)
    # The C runtime a glibc Rust binary loads (no shell: ask ldconfig, which glibc ships).
    out=$(tool ldconfig -p) || fail "ldconfig -p"
    grep -q 'libc.so.6' <<<"$out" || fail "no libc.so.6"
    grep -q 'libgcc_s.so.1' <<<"$out" || fail "no libgcc_s.so.1"
    ;;
  python-ssh)
    # The Job's path: `python3 main.py` runs ssh (OpenSSH prints its version on stderr).
    out=$(tool ssh -V 2>&1) || fail "ssh -V: $out"
    grep -q '^OpenSSH_' <<<"$out" || fail "ssh -V printed: $out"
    out=$(docker run --rm --entrypoint python3 "$ref" -c '
import pwd, os, subprocess
assert pwd.getpwuid(os.getuid()).pw_name == "janitor"
r = subprocess.run(["ssh", "-V"], capture_output=True, text=True, check=True)
assert r.stderr.startswith("OpenSSH_"), r.stderr
# ssh resolves the running uid and parses its (empty) config without a config file.
r = subprocess.run(["ssh", "-G", "example.invalid"], capture_output=True, text=True, check=True)
assert "user janitor" in r.stdout, r.stdout[:200]
print("ssh ok")') || fail "python3 -> ssh: $out"
    [[ "$out" == "ssh ok" ]] || fail "ssh check printed: $out"
    # No shebang audit, as for python and tesseract: without /usr/bin/env the CPython stdlib's
    # `#!/usr/bin/env python3` modules (base64.py, tarfile.py, ...) count as broken, and they
    # are only ever imported.
    ;;
  tesseract)
    out=$(tool tesseract --version 2>&1) || fail "tesseract --version"
    grep -q '^tesseract 5' <<<"$out" || fail "not tesseract 5: $out"
    out=$(tool tesseract --list-langs 2>&1) || fail "tesseract --list-langs"
    grep -qx 'eng' <<<"$out" || fail "no eng traineddata: $out"
    # The service's path: Python runs tesseract on a page (a blank PGM) and reads TSV.
    out=$(docker run --rm "$ref" -c '
import subprocess
open("/tmp/b.pgm", "wb").write(b"P5 64 32 255\n" + bytes([255]) * 64 * 32)
r = subprocess.run(["tesseract", "/tmp/b.pgm", "stdout", "--psm", "11", "tsv"], capture_output=True, text=True, check=True)
assert r.stdout.startswith("level"), r.stdout[:80]
print("ocr ok")') || fail "python -> tesseract tsv: $out"
    [[ "$out" == "ocr ok" ]] || fail "ocr check printed: $out"
    # The vendored fast model, as the OCR service runs it (no configs dir there).
    out=$(docker run --rm "$ref" -c '
import subprocess
open("/tmp/b.pgm", "wb").write(b"P5 64 32 255\n" + bytes([255]) * 64 * 32)
r = subprocess.run(["tesseract", "/tmp/b.pgm", "stdout", "--tessdata-dir", "/usr/share/tessdata-fast", "--psm", "11", "-c", "tessedit_create_tsv=1"], capture_output=True, text=True, check=True)
assert r.stdout.startswith("level"), r.stdout[:80]
print("fast ok")') || fail "fast model tsv: $out"
    [[ "$out" == "fast ok" ]] || fail "fast model check printed: $out"
    ;;
  sabnzbd-base)
    # SABnzbd's Python: 3.14 as python3, with the stdlib modules it needs.
    out=$(tool python3 -c '
import sys, ssl, sqlite3, ctypes, zoneinfo, lzma, bz2, zlib, json, uuid
assert sys.version_info[:2] == (3, 14), sys.version
zoneinfo.ZoneInfo("Europe/London")
for lib in ("libstdc++.so.6", "libgcc_s.so.1", "libgomp.so.1"):
    ctypes.CDLL(lib)  # what unrar and par2cmdline-turbo (built by sabnzbd-image) link
print("python ok", ssl.OPENSSL_VERSION)' 2>&1) || fail "python3 check: $out"
    [[ "$out" == "python ok OpenSSL "* ]] || fail "python3 check printed: $out"
    # 7-Zip as SABnzbd looks for it (`7zz` on PATH).
    out=$(tool 7zz i 2>&1) || fail "7zz i: $out"
    grep -q '^7-Zip' <<<"$out" || fail "7zz is not 7-Zip: $(head -1 <<<"$out")"
    # A round trip through 7zz, as uid 1000 in /tmp.
    out=$(tool python3 -c '
import os, subprocess
os.chdir("/tmp"); open("a.txt", "w").write("sabnzbd-base\n")
subprocess.run(["7zz", "a", "-bd", "-y", "t.7z", "a.txt"], check=True, capture_output=True)
os.remove("a.txt")
subprocess.run(["7zz", "x", "-bd", "-y", "t.7z"], check=True, capture_output=True)
print(open("a.txt").read().strip())' 2>&1) || fail "7zz round trip: $out"
    [[ "$out" == "sabnzbd-base" ]] || fail "7zz round trip printed: $out"
    # /config is the home and belongs to 1000.
    out=$(tool python3 -c 'import os; s = os.stat("/config"); print(s.st_uid, s.st_gid, os.path.expanduser("~"))') \
      || fail "stat /config"
    [[ "$out" == "1000 1000 /config" ]] || fail "/config: $out"
    if [[ "$variant" == "runtime" ]]; then
      shebang_audit
    else
      # sabnzbd-image builds unrar and par2cmdline-turbo (C++ with OpenMP) and installs
      # SABnzbd's requirements with uv.
      for cmd in "gcc --version" "g++ --version" "make --version" "uv --version" "xz --version" \
                 "bash --version" "python3 -m pip --version"; do
        # shellcheck disable=SC2086
        tool $cmd >/dev/null || fail "$cmd"
      done
      out=$(docker run -i --rm --entrypoint /bin/sh "$ref" \
        -c 'cd /tmp && cat > t.cpp && g++ -O2 -fopenmp -o t t.cpp && ./t' 2>&1 <<'CPP'
#include <omp.h>
#include <cstdio>
int main() { std::printf("omp %d\n", omp_get_max_threads() > 0); }
CPP
) || fail "g++ -fopenmp: $out"
      [[ "$out" == "omp 1" ]] || fail "g++ -fopenmp printed: $out"
    fi
    ;;
esac
echo "smoke ok: $image/$variant"
