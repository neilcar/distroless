# distroless

Distroless base images assembled with [apko](https://github.com/chainguard-dev/apko)
from [Wolfi](https://wolfi.dev) packages, pinned to exact **released** versions,
built for `linux/amd64` and `linux/arm64`, scanned, signed, and published to
`ghcr.io/neilcar/distroless/*`. Design:
[docs/superpowers/specs](docs/superpowers/specs/2026-10-24-distroless-base-images-design.md).

## Images

| Image | Lines | Contents |
|---|---|---|
| `ghcr.io/neilcar/distroless/static` | `latest` | CA certificates, tzdata, `/etc/passwd` with `nonroot` (65532). For static binaries. |
| `ghcr.io/neilcar/distroless/python` | every supported Python (today 3.11–3.15) | Python runtime only. `-dev` tags add busybox, pip and `uv` for build stages. |
| `ghcr.io/neilcar/distroless/nginx` | `mainline` (`stable` retired 2026-10-24) | nginx listening on **8080**, pid/temp files in `/tmp`, default server in `/etc/nginx/conf.d/default.conf` (replace it with yours). |
| `ghcr.io/neilcar/distroless/photoprism-base` | `latest` | PhotoPrism's runtime tools: ffmpeg, exiftool, libvips (`vips`, built here with lcms2 so `icc_transform` works), ImageMagick 7, libheif, libjxl, librsvg, the MariaDB client, sqlite, plus vendored darktable 5.6.2, RawTherapee 5.13 and yt-dlp under `/opt` (run through `/usr/bin/darktable-cli`, `rawtherapee-cli`, `yt-dlp`). Runs as **root**. `-dev` adds busybox, bash, GNU coreutils and tar, rsync, wget, curl, git, Go, Node.js 24, npm, make, gcc and the libvips/libheif headers. |
| `ghcr.io/neilcar/distroless/stash-base` | `latest` (versioned by Python 3.12) | Base for the shell-free Stash build: ffmpeg, ffprobe, libvips (`vips`, `vipsthumbnail`; the same lcms2 build as photoprism-base), exiftool and perl, Python 3.12 as `python` and `python3` with pip, requests, requests-toolbelt, lxml, beautifulsoup4, tzlocal, regex, python-dateutil, pytz, plus vendored pure-Python wheels cloudscraper, mechanicalsoup, stashapi (stashapp-tools), apscheduler and dateparser. Runs as **1000** (`stash`, home `/config`). `-dev` adds busybox, bash, GNU coreutils, git, make, gcc, Go, Node.js 24 and npm. |
| `ghcr.io/neilcar/distroless/tesseract` | `latest` (versioned by Wolfi's tesseract) | Tesseract 5 OCR with English traineddata (Wolfi's standard model, plus the vendored `tessdata_fast` 4.1.0 English model in `/usr/share/tessdata-fast`), and Python 3.12 (the entrypoint) for a small OCR service; `OMP_THREAD_LIMIT=1`. Runtime only. |
| `ghcr.io/neilcar/distroless/sabnzbd-base` | `latest` (versioned by Python 3.14) | Base for the shell-free SABnzbd build ([neilcar/sabnzbd-image](https://github.com/neilcar/sabnzbd-image)): Python 3.14 as `python3`, 7-Zip (`7zz`), and libstdc++, libgcc and libgomp for the unrar and par2cmdline-turbo that image builds from source. Runs as **1000** (`sabnzbd`, home `/config`). `-dev` adds busybox, bash, gcc/g++, make, glibc headers, pip, `uv` and xz. |
| `ghcr.io/neilcar/distroless/servarr-base` | `latest` (versioned by libicu79) | Base for the shell-free Servarr apps ([neilcar/servarr-image](https://github.com/neilcar/servarr-image)): Prowlarr, Radarr, Sonarr, Whisparr and Lidarr's self-contained .NET builds. Only what they load: ICU 79, OpenSSL, zlib, SQLite, libstdc++/libgcc, the CA bundle and tzdata, plus chromaprint's static `fpcalc` 1.6.2 (vendored, for Lidarr). Runs as **1000** (`servarr`, home `/config`). Runtime only. |
| `ghcr.io/neilcar/distroless/beets-base` | `latest` (versioned by python-3.12), `latest-dev` | Base for the shell-free beets image ([neilcar/pyapps-image](https://github.com/neilcar/pyapps-image)): Python 3.12, tini (PID 1, reaps the auto-import workers), Wolfi ffmpeg/ffprobe, flac/metaflac, ImageMagick 7 (`magick`), the CA bundle and tzdata, plus chromaprint's static `fpcalc` 1.6.2 (vendored, as servarr-base). Runs as **1000** (`beets`, home `/config`). The dev variant adds pip, uv, busybox and bash for pyapps-image's build stage. |
| `ghcr.io/neilcar/distroless/flaresolverr-base` | `latest` (versioned by chromium), `latest-dev` | Base for the shell-free FlareSolverr image ([neilcar/pyapps-image](https://github.com/neilcar/pyapps-image)): Python 3.11, Wolfi Chromium with its chromedriver (start `/usr/lib/chromium/chrome` directly: `/usr/bin/chromium` is a shell launcher), Xvfb, dumb-init and DejaVu fonts. The only image allowed two unreleased packages, because Wolfi has never released them (`avahi-libs`, `font-opensans`; see `IMAGE_UNRELEASED_ALLOWED`). Runs as **1000** (`flaresolverr`, home `/config`). The dev variant adds pip, uv, busybox and bash. |
| `ghcr.io/neilcar/distroless/jdownloader-base` | `latest` (versioned by openjdk-21-jre), `latest-dev` | Base for the shell-free headless JDownloader image ([neilcar/jdownloader-image](https://github.com/neilcar/jdownloader-image)): OpenJDK 21's JRE (`/usr/bin/java`, `JAVA_HOME`), tini, Wolfi ffmpeg/ffprobe, libstdc++/libgcc. Runs as **1000** (`jdownloader`, home `/config`). The dev variant adds busybox, bash and curl. |
| `ghcr.io/neilcar/distroless/debug` | `latest` (versioned by bash), variant `tools` only (tags end in `-tools`) | Break-glass toolbox for troubleshooting shell-free containers with `kubectl debug --target=<container>` or a temporary sidecar, used only with the owner's OK each time: bash, coreutils, findutils, grep, sed, gawk, procps, less, file, tar, gzip, util-linux, nsenter, curl, openssl, jq, yq, sqlite3, dig, netcat, iproute2 (`ss`, `ip`), tcpdump, strace and lsof. It has a shell, so it has no `runtime` variant. Runs as **0** to reach a target's files through `/proc/<pid>/root`. |
| `ghcr.io/neilcar/distroless/python-ssh` | `latest` (versioned by Python 3.12) | Python 3.12 (the entrypoint, also as `python3`) and the OpenSSH client (`ssh`, `scp`, `sftp`), for small stdlib scripts that shell out to `ssh` (the lxdk8s feral-janitor Job). Runs as **1000** (`janitor`, home `/tmp`). `-dev` adds busybox. |
| `ghcr.io/neilcar/distroless/ci-tools` | `latest` (versioned by curl), variant `tools` only (tags end in `-tools`) | busybox and curl for CI smoke tests (hey-furby's `image.yml`), in place of Docker Hub's `busybox` and `curlimages/curl`. The entrypoint is curl, as in `curlimages/curl`; run busybox applets with `--entrypoint chown` and the like (`-u 0` for root). It has a shell, so it has no `runtime` variant. Runs as **65532**. |
| `ghcr.io/neilcar/distroless/valkey` | `latest` (versioned by Valkey 9.0) | Valkey, the Redis-compatible server (Wolfi has no Redis), with `valkey-cli`, for photoprism-k8s's CI Redis service. With no arguments it runs as the official redis image does with no config: protected mode off, data in `/data`. Pass your own arguments to replace that. Runs as **999** (`valkey`, home `/data`), like photoprism-index-redis's pod. Runtime only. |
| `ghcr.io/neilcar/distroless/rust` | `latest` (versioned by the newest Rust), variant `dev` only (tags end in `-dev`) | Build image: Rust (cargo, rustc, clippy, rustfmt), gcc and glibc headers for crates that build C, git and busybox (`/bin/sh`, the entrypoint). `CARGO_HOME=/usr/local/cargo`. Binaries link glibc, so run them on `cc`. Runs as **0**, since GitHub job containers write the runner's workspace. |
| `ghcr.io/neilcar/distroless/cc` | `latest` (versioned by libgcc) | `static` plus glibc and libgcc, for dynamically linked Rust and C binaries (ollama-orchestrator). |

Runtime images have no shell and no package manager and run as uid **65532**
(`photoprism-base`: uid **0**, the owner's decision; `debug`: uid **0**, to reach a debug target's files; `stash-base`, `sabnzbd-base`, `servarr-base`, `beets-base`, `flaresolverr-base`, `jdownloader-base` and `python-ssh`: uid **1000**, as their apps' pods; `valkey`: uid **999**, as photoprism-index-redis's pod).

`stash-base` also has a vendor layer: five pure-Python wheels from PyPI (pinned by
version and sha256 in `catalog.yaml`) unpacked into `/usr/lib/python3.12/site-packages`,
plus the launcher as `/usr/bin/env` in the runtime variant (so `#!/usr/bin/env python3`
plugins run). Unlike the AppImages, Trivy reads those wheels' metadata, so their findings
are gated like any package's; `dl vendor-check` (in the daily rescan) opens the same
*Vendored tool updates available* issue when PyPI has a newer final release.

`photoprism-base` has one layer that is not a Wolfi package: darktable, RawTherapee
and yt-dlp from their upstream release files (pinned by sha256 in `catalog.yaml`,
written to `locks/photoprism-base/latest/vendor.json`), unpacked without their
AppRun shell scripts and started by a small Go launcher (`launcher/`). The launcher
is also installed as a minimal `/usr/bin/env` in the runtime variant (assignments and a
command, no options; `-dev` keeps busybox's env),
so `#!/usr/bin/env perl` scripts such as exiftool run without coreutils. It is
appended to the apko image before the scan, so the scanned digest is the pushed one.
Trivy findings under `/opt/darktable`, `/opt/rawtherapee` and `/opt/yt-dlp` are
listed in a separate *Vendored (not gated)* section of the gate summary (Trivy cannot
see inside those files, so it is normally empty; see [Scan gate](#scan-gate)), and the
layer's contents are attested per arch (predicate type
`https://github.com/neilcar/distroless/vendor-layer/v1`).

### Tags

| Example | Meaning |
|---|---|
| `python:3.12` / `nginx:stable` / `static:latest` | moves with every rebuild of that line |
| `nginx:1.30` | the newest build of nginx 1.30.x (stops moving if `stable` moves to a new minor) |
| `python:3.12.15` | newest build of that upstream version |
| `python:3.12.15-1a2b3c4d` | one exact build (the suffix hashes the lock file, so it changes when any package changes) |
| `…-dev` | the same, for the `-dev` variant |

Builds are reproducible: rebuilding an unchanged lock produces the same digest
(the `org.opencontainers.image.revision` annotation is the last commit that changed
that line's lock or config), so Dependabot only proposes real changes.

Pin consumers by tag **and** digest (`python:3.12@sha256:…`) and let Dependabot
bump the digest. Ignore minor/major updates for these images in Dependabot so it
never moves you to another line.

### Verify

Images are signed keylessly with cosign and carry SPDX SBOM attestations (index
and per arch). Use cosign v3 or newer:

```bash
cosign verify ghcr.io/neilcar/distroless/python:3.12 \
  --certificate-identity-regexp '^https://github.com/neilcar/distroless/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
cosign verify-attestation --type spdxjson ghcr.io/neilcar/distroless/python:3.12 \
  --certificate-identity-regexp '^https://github.com/neilcar/distroless/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

### Debugging a shell-free container with `debug`

Break glass only, with the owner's OK each time. Pin the index digest that the
`latest-tools` tag points to. A per-arch manifest digest runs that arch on every
node, which fails with `exec format error` on the other one.

```bash
kubectl -n apps debug <pod> --target=<container> --container=dbg1 --profile=general \
  --image=ghcr.io/neilcar/distroless/debug@sha256:<index digest> -- sleep 900
kubectl -n apps exec -it <pod> -c dbg1 -- bash
```

The debug container shares the target's process and network namespaces, so
`ps`, `curl localhost:<port>` and `/proc/<pid>/root/...` (the target's files)
work as the pod's own user. strace needs root, so add
`--custom root.json` with
`{"securityContext":{"runAsUser":0,"runAsGroup":0,"runAsNonRoot":false}}`.
tcpdump needs `--profile=netadmin` and the same root file. The lxdk8s Kyverno
exception `debug-toolbox-capabilities` lets only this image, pinned by digest,
add SYS_PTRACE, NET_RAW and NET_ADMIN to ephemeral containers. Each container
name can be used once, and ephemeral containers stay in the pod until it's
recreated.

## How it stays current

- **Sync** (daily 06:17 UTC, `sync.yml`): `dl sync` reads the Wolfi index for both
  arches and [endoflife.date](https://endoflife.date/python), picks the supported
  lines and each line's newest *released* version, and renders
  `locks/<image>/<line>/<variant>.apko.yaml`. Every config is re-locked with
  `apko lock`; any dependency that resolved to a pre-release or `_git` snapshot is
  pinned to its newest release (`dl pin-released`) and re-locked. Changes are
  committed to `main`, which triggers the build. New lines are added
  automatically; lines that reach end of life stop building but stay published.
- **Build** (`build.yml`): for each changed image/line/variant — `apko build`
  from the lock, smoke test, Trivy scan of the exact OCI layout that gets pushed,
  the scan gate, `crane push`, a check that the pushed manifests are the scanned
  ones, tags, `cosign sign`, SBOM attestations.
- **Rescan** (daily 07:47 UTC, `rescan.yml`): re-scans every published image with
  a fresh Trivy database; new Critical/High findings open an issue, and findings
  with an available fix trigger a sync.
- Failures, blocked lines, new/retired lines and nginx minor-version moves open
  or update a GitHub issue labelled `automation`.

### Scan gate

A build is published only if, per arch:

1. no Critical/High finding has an **available fix** — a released Wolfi version
   (on both arches) at or above the advisory's fixed version. Fixes that exist only
   as snapshots or unpublished versions are listed as notes, not blockers;
2. it has no more findings at any severity than the image currently published
   for that tag.

Findings in vendored files (`photoprism-base`'s `/opt/...`) count toward neither rule.
In practice that section is empty: Trivy cannot see the libraries bundled inside the
vendored AppImages and the PyInstaller yt-dlp binary, so their CVEs are not scanned at
all. New upstream releases are tracked by the vendor release watcher instead, and the
gate summary says so every time.

Exceptions go in [`.trivyignore`](.trivyignore), which only the owner edits.

### Local melange packages

Three packages live in `melange/`:

- `distroless-nginx-config` replaces Wolfi's port-80 nginx config.
- `distroless-no-shell` is an empty package that provides `cmd:bash`. ffmpeg's
  `libsrt` depends on bash only for unused `srt-*` scripts; the `photoprism-base`
  runtime variant installs this instead so the image stays shell-free (the `-dev`
  variant keeps real bash).
- `distroless-libvips` (and `-dev`, `-doc`) is libvips built from the upstream release
  tarball (pinned by sha256) with lcms2. Wolfi's libvips has no lcms2, so it cannot
  convert Display P3 / Adobe RGB photos to sRGB. It keeps Wolfi's version and build
  options and provides what `libvips` / `libvips-dev` provide; `photoprism-base`
  installs it instead and is versioned by it. Sync opens an `automation` issue
  "distroless-libvips is behind Wolfi libvips <version>" whenever Wolfi's newest released
  libvips is newer; bump `version` and `expected-sha256` in the melange file to follow.
  `dl lock-check` fails any photoprism-base or stash-base lock that contains Wolfi's
  `libvips` or `libvips-dev`. stash-base installs distroless-libvips too.

The `packages.yml` workflow builds every `melange/*.yaml` with a throwaway signing
key and commits the signed packages (`packages/`) and public key
(`melange.rsa.pub`); no private key is stored anywhere.

## Results (2026-10-24)

Trivy, Critical/High/Medium/Low, same database for each before/after pair.

| Base image | C/H/M/L | Note |
|---|---|---|
| `static:latest` | 0/0/0/0 | |
| `python:3.11`, `3.12`, `3.15` | 0/0/1/0 | zlib; fix only in a release candidate |
| `python:3.13` | 0/2/7/0 | Highs fixed only in a `_git` snapshot |
| `python:3.14` | 0/0/9/0 | |
| `nginx:mainline` | 0/0/1/0 | zlib, as above |
| `nginx:stable` | 0/6/7/0 | 3 unique Highs (counted twice: nginx + mime-types); public Wolfi stopped at 1.30.2, fixes are in 1.30.3–1.30.5 builds that aren't published |
| `servarr-base:latest` | 0/0/1/0 | zlib, as above |

| Consumer | Before | After | |
|---|---|---|---|
| trakt-clean (`python:3.12-slim` → `python:3.12`) | 0/44/63/62 | 0/0/1/0 | switched |
| tailnet-egress-watcher (`distroless/static-debian12`) | 0/0/0/0 + 3 unrated Debian advisories | 0/0/0/0 | switched |
| node-capacity-watcher (`distroless/static`) | 0/0/0/0 | 0/0/0/0 | switched |
| atpass-web (`nginx:1.30-alpine-slim` → `nginx:mainline`) | 0/0/0/0 | 0/0/1/0 | switched; the zlib Medium also affects Alpine's zlib 1.3.2-r1, but Alpine's feed only lists CVEs once fixed |
| Stash v0.31.1 (`stashapp/stash` → [`neilcar/stash`](https://github.com/neilcar/stash-image) on `stash-base`) | 13/78/44/6 | 0/2/3/1 | switched 2026-10-25; cluster trivy-operator report. CI Trivy with every package type (Go modules included): 13/190/191/56 → 0/21/24/1 |
| PhotoPrism index Jobs 261007 (`photoprism-k8s`, Ubuntu → [`neilcar/photoprism-index`](https://github.com/neilcar/photoprism) on `photoprism-base`) | 12/288/3202/638 | 3/5/9/0 | switched 2026-10-25; CI Trivy, non-vendored findings (vendored darktable/RawTherapee/yt-dlp files are not seen by Trivy). The PhotoPrism server moved too (next row). All Criticals and Highs left are in the MariaDB 11.8 client, replaced by 13.1 in #43 (applies when the index image is rebuilt) |
| PhotoPrism app pod 261007 (`photoprism/photoprism` → `neilcar/photoprism` on `photoprism-base`: the official Plus binary, libraries and assets copied unchanged, built by `image-app.yml` in neilcar/photoprism-k8s; private) | 12/288/3594/692 | 0/0/1/0 | switched 2026-11-01, read-only root, still uid 0; CI Trivy, non-vendored findings. The copied `/opt/photoprism` files score the same in both (0/6/13/1). Copied rather than built because a source build lacks the Plus code (the User role); moves only with the fork's release |
| Servarr apps (linuxserver / hotio → [`neilcar/<app>`](https://github.com/neilcar/servarr-image) on `servarr-base`, same versions) | Prowlarr 2/19/8/44, Radarr 2/23/10/44, Sonarr 1/14/8/44, Whisparr (hotio) 2/11/3/0, Lidarr 2/23/10/44 | Prowlarr 2/18/8/0, Radarr 2/22/10/0, Sonarr 0/12/7/0, Whisparr 2/11/4/0, Lidarr 2/22/10/0 | switched 2026-10-29/30 (Prowlarr, Radarr, Sonarr, Whisparr, Lidarr), each permanent after a 4-hour soak; CI Trivy amd64 from each `<app>-v<version>` release. The OS packages go (the only one left is zlib's Medium); the Criticals and most Highs are in the .NET runtime and libraries the publishers bundle, which only a new upstream release fixes. Trivy counts one High and one Medium more in our Prowlarr/Radarr/Lidarr bundles than in linuxserver's, from the same publisher build. These counts are unique (CVE, package) pairs from CI Trivy, so they aren't comparable with the Stash row's trivy-operator counts, which count each bundled file. hotio's 0 OS findings is likely Alpine's feed listing CVEs only once fixed (as for atpass-web), not a clean image |

## Development

```bash
uv sync
uv run pytest
uv run dl --help
```
