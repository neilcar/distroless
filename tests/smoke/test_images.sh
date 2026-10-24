#!/usr/bin/env bash
# Smoke-test a locally loaded image. Usage: test_images.sh <image-ref> <image> <variant>
set -euo pipefail
ref=$1 image=$2 variant=$3
fail() { echo "SMOKE FAIL ($image/$variant): $*" >&2; exit 1; }

user=$(docker inspect --format '{{.Config.User}}' "$ref")
if [[ "$image" == "photoprism-base" ]]; then  # runs as root (owner's decision)
  [[ "$user" == "0" || "$user" == "root" || "$user" == "0:0" ]] || fail "user is '$user'"
else
  [[ "$user" == "65532" || "$user" == "nonroot" || "$user" == "65532:65532" ]] || fail "user is '$user'"
fi

has_file() { docker run --rm --entrypoint "" "$ref" "$@" >/dev/null 2>&1; }
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
    tool() { docker run --rm --entrypoint "$1" "$ref" "${@:2}"; }
    for cmd in "ffmpeg -version" "exiftool -ver" "heif-dec --version" "magick -version" \
               "vips --version" "djxl --version" "rsvg-convert --version" "mariadb --version" \
               "yt-dlp --version"; do
      # shellcheck disable=SC2086  # each entry is "tool args"
      tool $cmd >/dev/null || fail "$cmd"
    done
    if [[ "$variant" == "runtime" ]]; then
      # Every script must find its interpreter (no shell in the image, so look from outside).
      root=$(mktemp -d)
      cid=$(docker create --entrypoint /none "$ref")
      docker export "$cid" | tar -x -C "$root" --exclude='dev' --exclude='dev/*'
      docker rm "$cid" >/dev/null
      image_path=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$ref" \
        | sed -n 's/^PATH=//p')
      python3 -I "$(dirname "$0")/shebang_audit.py" "$root" "${image_path:-/usr/sbin:/sbin:/usr/bin:/bin}" \
        || fail "scripts whose interpreter is missing (see above)"
      rm -rf "$root"
    fi
    out=$(tool darktable-cli --version) || fail "darktable-cli --version"
    grep -q '5\.6\.2' <<<"$out" || fail "darktable-cli is not 5.6.2: $out"
    out=$(tool rawtherapee-cli -v || true)  # upstream prints the version, then exits 255
    grep -q '5\.13' <<<"$out" || fail "rawtherapee-cli is not 5.13: $out"
    if [[ "$variant" == "dev" ]]; then
      for cmd in "go version" "node --version" "make --version" "bash --version"; do
        # shellcheck disable=SC2086
        tool $cmd >/dev/null || fail "$cmd"
      done
    fi
    ;;
esac
echo "smoke ok: $image/$variant"
