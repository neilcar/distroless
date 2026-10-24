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
| `ghcr.io/neilcar/distroless/photoprism-base` | `latest` | PhotoPrism's runtime tools: ffmpeg, exiftool, libvips (`vips`), ImageMagick 7, libheif, libjxl, librsvg, the MariaDB client, sqlite, plus vendored darktable 5.6.2, RawTherapee 5.13 and yt-dlp under `/opt` (run through `/usr/bin/darktable-cli`, `rawtherapee-cli`, `yt-dlp`). Runs as **root**. `-dev` adds busybox, bash, Go, Node.js, make, gcc and the libvips/libheif headers. |

Runtime images have no shell and no package manager and run as uid **65532**
(`photoprism-base`: uid **0**, the owner's decision).

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

Two config-only packages live in `melange/`:

- `distroless-nginx-config` replaces Wolfi's port-80 nginx config.
- `distroless-no-shell` is an empty package that provides `cmd:bash`. ffmpeg's
  `libsrt` depends on bash only for unused `srt-*` scripts; the `photoprism-base`
  runtime variant installs this instead so the image stays shell-free (the `-dev`
  variant keeps real bash).

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

| Consumer | Before | After | |
|---|---|---|---|
| trakt-clean (`python:3.12-slim` → `python:3.12`) | 0/44/63/62 | 0/0/1/0 | switched |
| tailnet-egress-watcher (`distroless/static-debian12`) | 0/0/0/0 + 3 unrated Debian advisories | 0/0/0/0 | switched |
| node-capacity-watcher (`distroless/static`) | 0/0/0/0 | 0/0/0/0 | switched |
| atpass-web (`nginx:1.30-alpine-slim` → `nginx:mainline`) | 0/0/0/0 | 0/0/1/0 | switched; the zlib Medium also affects Alpine's zlib 1.3.2-r1, but Alpine's feed only lists CVEs once fixed |

## Development

```bash
uv sync
uv run pytest
uv run dl --help
```
