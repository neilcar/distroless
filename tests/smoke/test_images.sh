#!/usr/bin/env bash
# Smoke-test a locally loaded image. Usage: test_images.sh <image-ref> <image> <variant>
set -euo pipefail
ref=$1 image=$2 variant=$3
fail() { echo "SMOKE FAIL ($image/$variant): $*" >&2; exit 1; }

user=$(docker inspect --format '{{.Config.User}}' "$ref")
if [[ "$image" == "photoprism-base" ]]; then  # runs as root (owner's decision)
  [[ "$user" == "0" || "$user" == "root" || "$user" == "0:0" ]] || fail "user is '$user'"
elif [[ "$image" == "stash-base" ]]; then  # Stash's pod runs as 1000:1000
  [[ "$user" == "1000" || "$user" == "stash" || "$user" == "1000:1000" ]] || fail "user is '$user'"
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
               "yt-dlp --version"; do
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
esac
echo "smoke ok: $image/$variant"
