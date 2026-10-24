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
| `ghcr.io/neilcar/distroless/nginx` | `stable`, `mainline` | nginx listening on **8080**, pid/temp files in `/tmp`, default server in `/etc/nginx/conf.d/default.conf` (replace it with yours). |

Runtime images have no shell and no package manager and run as uid **65532**.

### Tags

| Example | Meaning |
|---|---|
| `python:3.12` / `nginx:stable` / `static:latest` | moves with every rebuild of that line |
| `nginx:1.30` | the newest build of nginx 1.30.x (stops moving if `stable` moves to a new minor) |
| `python:3.12.15` | newest build of that upstream version |
| `python:3.12.15-1a2b3c4d` | one exact build (the suffix hashes the lock file, so it changes when any package changes) |
| `…-dev` | the same, for the `-dev` variant |

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

Exceptions go in [`.trivyignore`](.trivyignore), which only the owner edits.

### nginx config package

`distroless-nginx-config` (in `melange/`) replaces Wolfi's port-80 config. The
`nginx-config.yml` workflow builds it with a throwaway signing key and commits the
signed packages (`packages/`) and public key (`melange.rsa.pub`); no private key
is stored anywhere.

## Development

```bash
uv sync
uv run pytest
uv run dl --help
```
