# PhotoPrism app pod on distroless (official Plus binary) — design

Date: 2026-11-01. Part of Tier 1 of the distroless rollout (transmission was skipped by the owner).

## Why

The PhotoPrism server pod (`photoprism-photoprism` StatefulSet, namespace `photoprism`) runs
`docker.io/photoprism/photoprism:261007`: Ubuntu, s6 init, a shell, coreutils, apt and ~2.2 GB of
tooling, **as uid 0**, parsing untrusted media with ffmpeg, exiftool and libheif. It is the last
PhotoPrism piece on an upstream image; the maintenance/index Jobs already run the shell-free
`photoprism-index` image on `distroless/photoprism-base`.

## The owner's condition

**Keep the subscriber features, above all user management.** The owner said to skip PhotoPrism
unless that holds.

Finding (2026-11-01): a build from source cannot meet it. The official binary reports
`photoprism version 261007-65faaae5d-Linux-AMD64-Plus`; the Plus code is not in the open-source
tree. The open-source role list (`internal/auth/acl/roles.go`, `UserRoles`) has admin, guest,
visitor and none, but no `user` role, and the live account `kim` has role **User**. A source build
would not accept that role.

So the owner chose to **copy the official binary unchanged** instead of building it.

## Goals

- The app pod runs PhotoPrism's own official Plus binary, web assets and bundled libraries,
  byte-for-byte from `docker.io/photoprism/photoprism:<release>` pinned by digest, on
  `ghcr.io/neilcar/distroless/photoprism-base` (Wolfi, no shell).
- User management, kim's User login, the membership tier, maps and places behave exactly as now.
- No Ubuntu, s6, `/scripts`, shell, coreutils or package manager in the image.
- Image gates like the other distroless images: smoke test, ELF closure check, Trivy compared with
  the official image (no worse), cosign-signed with `--registry-referrers-mode=legacy`, Kyverno
  verify-images Enforce.

## Non-goals

- Rebuilding PhotoPrism from source for the app pod.
- Changing the index Jobs or their fork build.
- Moving the pod off root. It stays uid 0/gid 0 like the index Jobs (owner's earlier decision for
  `photoprism-base`; the storage volume is root-owned).
- MariaDB or Redis (Tier 3).

## Anti-goals (failure even if it "works")

- kim, or any non-admin account, can no longer log in, or its role changes.
- The instance shows as community edition, or loses its membership/tier.
- The app pod runs a newer PhotoPrism release than the index Jobs' fork (see Versions).
- The copied Plus binary ends up in a public image.

## What we know about the official image (2026-11-01, 261007, amd64)

- Index digest `sha256:0f85369636ad99ca9a1c33f2d04df6c590802d16b7c33b4a1ea026b595be06d1`
  (multi-arch).
- Entrypoint `/init` (s6) → `/scripts/entrypoint.sh` → `photoprism start`; user creation and chown
  from `PHOTOPRISM_UID/GID`. None of this is needed when the pod already runs as root.
- What PhotoPrism itself needs, all under `/opt/photoprism`:
  - `bin/photoprism` (73 MB). NEEDED: `libtensorflow.so.2 libvips.so.42 libgobject-2.0.so.0
    libglib-2.0.so.0 libc.so.6`, RPATH `$ORIGIN/../lib`, highest symbol GLIBC_2.34.
  - `lib/`: libtensorflow 2.18.0, libtensorflow_framework, libonnxruntime 1.29.1 (+ providers
    shared). Highest GLIBCXX_3.4.30.
  - `assets/` (260 MB): static web app, locales, models, profiles, samples.
  - `bin/photoprism-debug` is not needed.
- The image's default env is in its config. The `photoprism-index` Dockerfile's production stage
  already sets the same PhotoPrism defaults on `photoprism-base`.
- `photoprism-base` already carries libvips (`distroless-libvips`, with lcms2), glib, libstdc++,
  ffmpeg, exiftool, perl, libheif, ImageMagick 7, librsvg/rsvg-convert, the MariaDB 13.1 client,
  darktable and RawTherapee (vendored), and yt-dlp.

## Decided

- **Copy, don't build.** A new image `ghcr.io/neilcar/photoprism` is built from `photoprism-base`
  (runtime variant) plus
  `COPY --from=docker.io/photoprism/photoprism:<release>@<digest>` of `/opt/photoprism/bin/photoprism`,
  `/opt/photoprism/lib` and `/opt/photoprism/assets`. Nothing else comes from the official image.
- **Entry point:** `photoprism start` directly (`ENTRYPOINT ["/opt/photoprism/bin/photoprism"]`,
  `CMD ["start"]`), with the same `ENV` block as the `photoprism-index` production stage.
- **Private package.** Only the cluster pulls it, with the existing `ghcr-pull` secret.
- **Versions (owner):** the app follows the **fork**, not upstream. It moves to a new release only
  when the index fork moves to the same release, so both always run the same PhotoPrism version
  and database schema. There is no automatic upstream watcher for this image.
- **Proof on the live pod (owner, 2026-11-01).** No second instance: a second copy of the
  membership credentials could make the membership server refresh or rotate the live session. One
  lxdk8s commit switches the live pod (same storage, same membership), and right after it rolls:
  1. the edition string ends in `-Plus`;
  2. `/api/v1/config` reports the same membership/tier as before the switch (record it first);
  3. kim's account lists with role User (`photoprism users ls`);
  4. the owner (or kim) logs in by hand as kim, and maps and places load.
  If any check fails, revert the lxdk8s commit at once; PhotoPrism stays on the official image.
  A few minutes of downtime is accepted.
- **Leaving it switched (owner):** checks 1–3 passing plus the owner's own login working is enough;
  no separate final OK is needed.
- **Trivy gate (my call):** the copied `/opt/photoprism` files are identical in both images, so they
  count as vendored, like `/opt/darktable` and `/opt/rawtherapee` today. The rest of the image must
  be no worse than the official image in every severity, the Tier 2 bar.
- **Privacy (my call):** the fork repo is private. A pre-publish check refuses to push if the
  `ghcr.io/neilcar/photoprism` package is not private.
- **Things that run a shell in the app pod today (found 2026-11-01; all fixed before the switch):**
  - `parallel-index.sh` `check_idle` (bash: `/proc` scan + faces lock) and `db_connections_left`
    (sh + `mariadb` with the pod's credentials), run by the nightly maintenance driver. *My call:*
    the app image also carries `/opt/parallel-index/bin/parallel-index` (the fork workflow already
    builds it), with new in-pod subcommands `pod idle` and `pod db-connections-left`;
    `parallel-index.sh` uses them and falls back to the bash version when the binary is absent
    (official image), so rollback keeps working.
  - `photoprism-maintenance/ppsummary.sh` (bash with find/sha1sum/awk). *Owner: port it.* The
    in-pod work moves to `parallel-index pod count-files` and `parallel-index pod claims`; the
    summing stays on the caller's side.
  - `apple-photos-export/sync-favorites.py` (`cat` of a rendered sidecar JPG). *My call:* fetch it
    through the PhotoPrism API instead.
  - `apple-photos-export/read-capture-times.sh` (`sh -c 'cd … && exiftool …'`). *My call:* pass
    absolute paths to `exiftool -@ -`; no shell needed.
  Each works against both the official and the new image.
- **Deploy through Fleet** (`lxdk8s/fleet/photoprism`, chart `photoprism-plus`): image override in
  `photoprism-values.yaml`, plus whatever the chart needs to pull a private image.
- **Rollback:** one lxdk8s revert to the official image.

## Left to the builder

- Where the image is built. Default: the fork's existing Wolfi workflow
  (`docker/photoprism/wolfi/`, `.github/workflows/image-wolfi.yml` on `k8s-261007-skip-fixes`),
  as a second target beside `photoprism-index`, so a fork rebase updates both together.
- Architectures. The pod is pinned to amd64; build both if the workflow already does, otherwise
  amd64 only.
- When to switch: outside the nightly vision-caption window (00:15–06:00 ET) and not while an
  index Job is running.
- **Pull secret:** the `photoprism-plus` chart (owner's repo `neilcar/photoprism-plus-chart`) has
  no `imagePullSecrets` in its StatefulSet template. Add it to the chart (bump, publish, re-pin in
  fleet.yaml), or set it on the pod's ServiceAccount. Wiring the chart's dead
  `resources/affinity/nodeSelector/tolerations` values is optional while in there.
- **Read-only root:** set `readOnlyRootFilesystem: true` with a `/tmp` emptyDir if PhotoPrism runs
  cleanly that way; otherwise leave it writable and note it.
- The Kyverno change: add the app pod (app.kubernetes.io/name of the chart) to
  `neilcar-workloads-use-neilcar-images` for namespace `photoprism`, and a verify-images entry for
  `ghcr.io/neilcar/photoprism`, tested against all policies and exceptions.
- What the smoke test checks beyond `photoprism --version` (e.g. `photoprism start` reaches
  `/api/v1/status` against SQLite, TensorFlow and ONNX libraries load, ffmpeg/exiftool resolve).
