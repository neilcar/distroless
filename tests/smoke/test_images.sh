#!/usr/bin/env bash
# Smoke-test a locally loaded image. Usage: test_images.sh <image-ref> <image> <variant>
set -euo pipefail
ref=$1 image=$2 variant=$3
fail() { echo "SMOKE FAIL ($image/$variant): $*" >&2; exit 1; }

user=$(docker inspect --format '{{.Config.User}}' "$ref")
[[ "$user" == "65532" || "$user" == "nonroot" || "$user" == "65532:65532" ]] || fail "user is '$user'"

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
    ;;
  static)
    dir=$(mktemp -d)
    (cd "$(dirname "$0")" && CGO_ENABLED=0 GOOS=linux go build -o "$dir/hello" hello.go)
    printf 'FROM %s\nCOPY hello /hello\nENTRYPOINT ["/hello"]\n' "$ref" > "$dir/Dockerfile"
    docker build -q -t smoke-static "$dir" >/dev/null
    [[ "$(docker run --rm smoke-static)" == "ok" ]] || fail "static binary"
    ;;
esac
echo "smoke ok: $image/$variant"
