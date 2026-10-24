# Distroless base images — design

Date: 2026-10-24
Owner: neilcar (GitHub), home cluster

## Intent

Build and publish my own distroless base images instead of using Chainguard's
free images. Reasons, in the owner's words: **pinning versions, control, and
to see if we can do it.** Chainguard's free tier only offers floating
`:latest` / `:latest-dev` tags; version pinning needs a paid subscription.

Success is judged by one thing: **the images that move onto these bases end up
with fewer vulnerabilities than they have today.** If vulnerabilities aren't
reduced, the project has failed even if everything builds and publishes.

## Goals

1. A new **public** GitHub repo, `neilcar/distroless`, that builds three
   distroless base images and publishes them as **public** packages on GHCR:
   - `ghcr.io/neilcar/distroless/static` — for statically linked binaries
     (the Go services): CA certificates, tzdata, `/etc/passwd` with a non-root
     user, nothing else.
   - `ghcr.io/neilcar/distroless/python` — a Python runtime for **every
     supported Python line** (see "Lines" below), plus a `-dev` variant per
     line for build stages (adds a shell, pip and `uv`). The runtime variant
     has no shell and no package manager.
   - `ghcr.io/neilcar/distroless/nginx` — nginx for **every supported nginx
     line** (today: stable 1.30 and mainline 1.31), for serving static files.
2. Every package in every image is **pinned to an exact version**, so the same
   definition produces the same image. Image tags carry the line and the
   pinned upstream version (e.g. `python:3.12`, `python:3.12.15`,
   `nginx:1.30`, `nginx:1.30.2`, `nginx:stable`/`mainline` aliases are the
   builder's call) plus something that changes when any other package in the
   image changes (builder's choice of scheme), and every published image is
   also addressable by digest. Consumers pin a line explicitly.
3. **Automatic bumps with no human approval.** When Wolfi publishes a newer
   version of a pinned package within a line (Python 3.12.x, nginx 1.30.x, CA
   bundle, tzdata, glibc, …), the repo updates the pin, rebuilds, scans and
   publishes on its own. A failed build or a failed scan gate stops the
   publish (see "Scan gate"); nothing broken or more vulnerable gets
   published.
4. **Multi-arch:** linux/amd64 and linux/arm64 (the cluster has Raspberry Pi
   and RK3588 nodes).
5. Each published image is **signed** (cosign, keyless via GitHub OIDC) and has
   an **SBOM** attached.
6. **Every image is scanned with Trivy before it is published.**
7. **Switch the consumers** onto the new bases, each via a PR in its own repo:
   - `neilcar/trakt-clean` — Python 3.12 app, multi-stage build with `uv`
     (build on `python-dev`, run on `python`). Also bump `certifi` in
     `uv.lock` (its current Critical, GHSA-6q48-6c7w-9gw2, is in the Python
     package, not the base).
   - `neilcar/atpass` — `web/Dockerfile`, static site currently on
     `nginx:1.30-alpine-slim` with `apk upgrade`; published to Docker Hub as
     `atpass-web`. **atpass-web moves from port 80 to 8080** (decided by the
     owner): update `web/nginx.conf`, `EXPOSE`, and every other reference in
     the atpass repo (README/docs, compose files, examples, tests), and call
     out the port change in the release notes as a breaking change for
     anyone running the image mapped to port 80.
   - `neilcar/tailnet-egress-watcher` and `neilcar/node-capacity-watcher` —
     Go binaries currently on `gcr.io/distroless/static*:nonroot`.
8. Consumers keep current automatically: their existing Dependabot setup
   (docker ecosystem) opens PRs when a new base is published. Images are
   public, so no registry credentials are needed.

## Success criteria (measured, not assumed)

Record a Trivy baseline for each consumer image **before** switching, and
compare after. The comparison goes in each consumer PR description.

| Consumer | Today (Trivy, 2026-10-23) | Must end up |
|---|---|---|
| trakt-clean (`python:3.12-slim`) | 1 Critical, 5 High, 16 Medium, 54 Low | strictly fewer at every severity; 0 Critical and 0 High expected |
| atpass-web (`nginx:1.30-alpine-slim`) | not yet measured — measure first | fewer than its baseline |
| tailnet-egress-watcher (`distroless/static-debian12:nonroot`) | 0 | still 0 |
| node-capacity-watcher (`distroless/static:nonroot`) | 0 | still 0 |

## Scan gate (decided by the owner)

- **Block** a publish on any Critical or High finding **that has a fixed
  version available** (Trivy with `--ignore-unfixed` for the blocking check;
  unfixed findings are still reported).
- **Never publish an image worse than the one currently published** for that
  line (compare counts per severity against the current published image).
- **Exceptions** (findings judged not exploitable) live in a `.trivyignore`
  (or VEX) file in the repo that only the owner edits — the automation never
  adds to it.
- **Daily re-scan** of every published image; when a new Critical/High
  appears, open (or update) a GitHub issue, and trigger a rebuild if a fixed
  package exists.

## Lines (decided by the owner: build every supported line)

- **Only released versions are ever built or pinned (decided by the
  owner).** That applies to every package in every image, not just the
  headline one: no `_git` snapshots, no alpha/beta/rc, no other pre-release
  builds. Wolfi ships `_git` snapshot builds between upstream releases (as of
  2026-10-24: python-3.13 newest is `3.13.16_git20261016`, newest release
  `3.13.15-r8`; python-3.14 newest is `3.14.8_git20261021`, newest release
  `3.14.7-r8`). The pin for a line is its newest released version, even when
  a newer snapshot exists. Newer Wolfi revisions (`-rN`) of the same released
  upstream version are fine and are picked up.
- **Python:** every line python.org lists as supported (bugfix or security)
  that has at least one released Wolfi build. As of 2026-10-24 that is
  **3.11, 3.12, 3.13, 3.14 and 3.15** (3.15.0 is released and Wolfi has
  `3.15.0-r0`); 3.10 reaches end of life this month and is excluded. The
  builder confirms against python.org / endoflife.date at build time.
- **nginx:** stable and mainline (Wolfi `nginx-stable` 1.30.2,
  `nginx-mainline` 1.31.8 today).
- **New lines** that become supported and available in Wolfi are added
  **automatically**.
- **Lines that reach end of life** stop being built; their last images stay
  published. The automation **never moves a consumer to a different line**.
- **Notifications:** any failed bump, failed scan gate, line reaching end of
  life, or new line added opens or updates a **GitHub issue** in the repo, so
  the owner hears about it the normal GitHub way.

## Non-goals

- Building packages from source. Packages come from **Wolfi**
  (`packages.wolfi.dev`), which is open and freely usable; the images are
  assembled from them, not compiled.
- Covering every runtime. Day one is static, python (all supported lines) and
  nginx (stable and mainline). More runtimes can be added later (the repo
  should make adding one straightforward).
- PhotoPrism (`photoprism-k8s`) — its runtime needs ffmpeg, exiftool, RAW
  converters, etc.; out of scope.
- The inactive forks/demo repos found in the survey.

## Anti-goals

- Not reducing vulnerabilities (see success criteria).
- Using Chainguard's free hosted images (`cgr.dev/chainguard/*`) anywhere, as
  a base or as a build stage. Chainguard's **open-source tooling** (`apko`)
  and the **Wolfi** package repository are fine.
- Shipping a shell or package manager in a runtime image.
- Running as root by default.
- An auto-bump that publishes an image which fails its scan gate.

## Decisions already made

- **Tooling (my call, owner delegated it):** images defined declaratively with
  `apko`, packages from Wolfi pinned to exact versions. Wolfi keeps many
  versions in its index (checked 2026-10-24: python-3.12 has 33, nginx-stable
  12, ca-certificates-bundle 17, tzdata 10), so exact pins are workable.
  Current latest: python-3.12 3.12.15-r6, nginx-stable 1.30.2-r0, uv 0.13.5-r1,
  glibc 2.43-r13.
- **Hosting:** GHCR under `neilcar`, public repo and public packages.
- **Updates:** fully automatic within each line, gated by build + scan.
- **Lines:** every supported line per image, new lines added automatically.
- **Scope includes switching the four consumers.**
- **Consumer PRs include deploy config in the same repo** that the switch
  affects (my call). trakt-clean **keeps running as uid 10001** (`USER 10001`
  in its Dockerfile) so its `/data` volume needs no change (my call). Rolling
  trakt-clean out on the cluster is part of the job, but ask the owner before
  deploying. atpass-web isn't deployed on the home cluster; it's published
  to Docker Hub.

## Constraints and context

- GitHub account `neilcar` (personal, not an org). Default branch `main`.
  Existing repos use GitHub Actions with `docker/build-push-action`, Trivy
  scans before push (`aquasecurity/setup-trivy`), and Dependabot.
- trakt-clean today runs as uid 10001 and writes to a `/data` volume
  (`DB_PATH=/data/trakt-clean.db`); it has a Python-based `HEALTHCHECK` and
  `CMD ["trakt-clean"]` (a venv entry point at `/app/.venv/bin`). It is
  deployed on the home cluster via `deploy/values-home.yaml`.
- atpass-web's nginx config is `web/nginx.conf`, currently `EXPOSE 80`.
- The Go watchers run as uid 65532 today.
- Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Ask before pushing or merging anything in the consumer repos.

## Left to the builder

- Repo layout, workflow structure, and how auto-bumps are implemented (e.g.
  `apko lock` files, a scheduled workflow that resolves newest versions within
  each pinned line and commits the result).
- Tag scheme details beyond "carries the upstream version and is addressable
  by digest".
- Whether the `-dev` variant exists only for python or for all three.
- The default non-root uid/gid for the bases (consumers can override with
  `USER`).
- nginx details beyond the port: temp/pid paths writable by the non-root
  user, default config shipped in the base.
- How often the scheduled bump runs, and how "supported line" lists are
  discovered (python.org/endoflife.date plus the Wolfi index).
