# Distroless PhotoPrism image for the parallel index jobs — design

Status: for owner review, 2026-10-24. Spans two repos: this one (`neilcar/distroless`, the base
image) and the PhotoPrism fork (`neilcar/photoprism-k8s`, branch `k8s-parallel-index`,
checked out at `~/code/home/photoprism`, remote `private`).

## Intent

The parallel index Jobs (`photoprism-index-plan`, `photoprism-index-partition`,
`-medium`, `-large`, and their retries) run `ghcr.io/neilcar/photoprism-k8s`, an
Ubuntu 26.04 image built from `docker/photoprism/resolute/Dockerfile`. The owner wants
those Jobs on a distroless image built from their own Wolfi bases, the same way
trakt-clean, atpass and the watchers moved: pinned released packages, no package
manager, **no shell**, kept current automatically. The owner's view: "no reason that
all the required tools can't be added to it."

It must handle the whole library: camera RAW, HEIC/HEIF and live photos, JPEG XL,
TIFF/PSD, and video. Nothing PhotoPrism does during indexing may be lost.

## Goals

1. **A `photoprism-base` image in this repo**: every runtime tool PhotoPrism uses while
   indexing and converting, and no PhotoPrism. linux/amd64 and linux/arm64 (index pods
   run on amd1/amd2 and on mona/rk1/rk2). Same pipeline as the other images: catalog
   entry, `dl sync` locks, released-only versions, Trivy gate, cosign signatures, SBOM
   attestations, Dependabot-friendly reproducible digests.
2. **Contents of the base** (the owner said all of these should be handled):
   - From Wolfi: ffmpeg (with its codecs: x265, dav1d, aom, libde265, libva), exiftool
     and perl, libheif with `heif-dec`/`heif-enc`, ImageMagick 7, libvips, libjxl tools
     (`djxl`), ghostscript, librsvg (`rsvg-convert`), the MariaDB 11.8 client
     (`mariadb`, `mariadb-dump`), sqlite, CA certificates, tzdata.
   - **darktable 5.6.2 and RawTherapee 5.13**, both required (the owner: "it should
     include both"). Neither is in Wolfi. Prebuilt binaries are allowed: use the
     official release AppImages (`Darktable-5.6.2-{x86_64,aarch64}.AppImage` from
     darktable-org/darktable `release-5.6.2`; `RawTherapee_5.13_*_release.AppImage`
     and `RawTherapee_5.13_arm64_release.AppImage` — both arches confirmed published),
     repackaged with melange as local packages, pinned by version
     and sha256.
   - **yt-dlp**, not in Wolfi: a melange package from a pinned release.
3. **A `parallel-index` Go program** in the fork, replacing the in-pod scripts
   `setup/kubernetes/parallel-index/scripts/plan.sh` (~500 lines) and `index.sh`
   (~400 lines). It is a separate binary, not `photoprism` subcommands (owner's
   decision), so the fork's changes to PhotoPrism itself stay small and rebase easily.
   Commands: `parallel-index plan` and `parallel-index index`.
4. **The fork's image built on the base**: PhotoPrism (with its bundled TensorFlow 2.18
   and ONNX Runtime 1.29.1 in `/opt/photoprism/lib`, and its models/assets) and
   `parallel-index` compiled on a Wolfi build image so they link against Wolfi's
   libraries, then copied onto `photoprism-base`. Published to GHCR from the fork's CI
   for amd64 and arm64.
5. **The index Jobs use it.** `parallel-index.sh` already supports `INDEX_IMAGE` (Jobs
   in a different image than the StatefulSet); the Jobs switch to the new image and to
   `parallel-index` as their command.

## Behaviour contract for `parallel-index`

It replaces the scripts, so everything that reads their output keeps working unchanged:
`parallel-index.sh`, the maintenance `driver.sh`, and the n8n "PhotoPrism maintenance"
workflow's SUMMARY parsing.

- Same settings and defaults (every variable in the README's Settings table that the
  pod scripts read), same plan file format, same claim layout under `CLAIM_ROOT`
  (atomic `mkdir`), same partition/class/weight/megapixel logic, same shared-work order.
- Same log lines that anything parses or a person relies on, in particular
  `resources: peak working set … of … (…%) with N workers`, the 60-second `progress:`
  lines, the plan's `scanning:` / `sampling:` lines, and the `OOM<TAB>folder` lines.
- Same exit codes: 0 indexed, 1 a folder failed, 3 no/too-small memory limit,
  4 blocked by another operation, 5 a folder ran out of memory. (137 stays the kernel's.)
- Same worker sizing: `min(CPU, (limit - BASE_MEM_MB) / WORKER_MEM_MB, MAX_WORKERS)`
  from the downward API and cgroup, setting `PHOTOPRISM_INDEX_WORKERS`, `GOMAXPROCS`,
  `PHOTOPRISM_DATABASE_CONNS`, `MALLOC_ARENA_MAX=2` for the `photoprism` children.
- Same use of `photoprism index|convert|thumbs`, and of `exiftool` for megapixels, so
  the plan's numbers match today's exactly.
- The things the scripts did with coreutils (`find`, `stat`, `file`, `numfmt`, `awk`,
  `xargs`, `mv` for `FIX_EXTENSIONS`, …) are done in Go. Nothing in the image is
  invoked through a shell.
- The cases in `test.sh` become Go tests, still against a stub `photoprism` and
  simulated cgroup limits. CI runs them in place of shellcheck + `test.sh` for the
  replaced scripts.

## Changes outside the image

- `parallel-index.sh` (runs in the maintenance driver on `alpine/k8s`, keeps its bash,
  `kubectl` and `jq`): the rendered Job command becomes the `parallel-index` binary
  instead of `bash /opt/parallel-index/scripts/{plan,index}.sh`, and the Jobs stop
  mounting the `scripts` ConfigMap (the program ships in the image). The `plan`
  ConfigMap mount stays.
- `photoprism-maintenance` (`driver.sh`, `deploy.sh`, ConfigMap `photoprism-index-driver`):
  stop shipping `scripts/plan.sh` and `scripts/index.sh`; set `INDEX_IMAGE` to the new
  image by tag and digest.
- `INDEX_IMAGE` defaults to the new image, so the Jobs always have `parallel-index`
  (the StatefulSet's official image does not). The bash scripts path is removed.
- The new image is published as **`ghcr.io/neilcar/photoprism-index`**; the Ubuntu
  `ghcr.io/neilcar/photoprism-k8s` keeps publishing unchanged as the rollback image and
  the Trivy baseline (pinned by digest at the time of the comparison).
- The PhotoPrism StatefulSet is not touched.

## Success criteria

1. One full maintenance run on the new image, compared with the last run on the current
   image: the same files indexed, the same previews created, no new failed partitions
   or errors in the SUMMARY. (Builder's call on how to diff it; DB counts of files and
   sidecar previews before/after are the obvious measure.) **The builder starts this run
   itself** (owner's decision), as a normal maintenance run, plus a forced re-convert of
   one folder with RAW files needing both darktable and the RawTherapee fallback. Stash
   batch Jobs are paused first and resumed only after the PhotoPrism Jobs have been
   finished for 30 minutes, as usual.
2. Each format converts in the new image on both arches, in a smoke test in CI: a RAW
   that darktable handles, a RAW that needs the RawTherapee fallback, HEIC (and a live
   photo), JPEG XL, TIFF, PSD, and a video that gets a preview/transcode.
3. Trivy Critical/High/Medium/Low lower than the current `photoprism-k8s` image (the
   owner's rule for every switch so far: don't switch if vulnerabilities aren't reduced),
   **counting the Wolfi-provided part of the image**. Libraries bundled inside the
   darktable and RawTherapee AppImages are scanned and **listed separately** in the
   report, not counted toward this rule (owner's decision, 2026-10-24): unlike Ubuntu's
   shared packages today, they are frozen at upstream's release and Trivy may not see
   all of them. The base gate likewise judges only the Wolfi packages and notes the
   AppImage findings.
4. No shell in the published image: no `sh`, `bash`, `busybox` or `ash` on disk.
5. **A release watcher**: a scheduled check opens or updates an `automation` issue when
   darktable or RawTherapee publishes a newer stable release than the pinned one (and
   when one with a fix for a listed AppImage finding exists), so the bundles do not go
   stale. Building both from source against Wolfi is a possible later step, not this
   project.

## Non-goals

- The PhotoPrism server (`photoprism-photoprism-0`, official `photoprism/photoprism`)
  stays as it is for now. The image need not run `photoprism start`, the web UI, WebDAV,
  backups or the upstream entrypoint/init scripts.
- The maintenance driver image (`alpine/k8s`) and `parallel-index.sh` stay bash.
- `photoprism dl` (`internal/photoprism/dl/cmd.go` shells out to bash for downloads) is
  not supported in this image; indexing never uses it.
- GPU/CUDA, llama.cpp and other optional PhotoPrism extras.

## Anti-goals

- A shell or busybox sneaking into the runtime image (a `-dev` build variant is fine).
- AppImage launchers that are shell scripts (`AppRun`) being kept: the packages must
  call the real binaries with their bundled libraries some other way.
- Silent loss of a format: a converter missing or broken must fail CI, not show up as
  missing previews after a run.
- Pre-release or snapshot versions of anything.
- Changing the plan's decisions (partitions, classes) as a side effect of the rewrite.

## Constraints and context

- **The image runs as root (uid/gid 0)** — owner's decision, 2026-10-24, an exception
  to the bases' uid 65532 default (the catalog needs a per-image `run-as` override).
  Checked: the StatefulSet runs as `runAsUser: 0`/`runAsGroup: 0` with
  `PHOTOPRISM_UID/GID=0` and umask 022, so storage (Longhorn RWX NFS) is root-owned and
  mostly not group-writable (538 of 593 top-level entries), and originals and sidecar are
  NFS shares on Reginald (192.168.1.4) written as root. A non-root index pod could not
  write previews, sidecars, thumbnails or `FIX_EXTENSIONS` renames. Moving to non-root
  would need the server moved too plus a chown of the NFS shares — out of scope. The Jobs
  keep the StatefulSet's hardening: all capabilities dropped, no privilege escalation,
  RuntimeDefault seccomp.
- PhotoPrism's `install` target downloads TensorFlow and ONNX Runtime with
  `scripts/dist/install-{tensorflow,onnx}.sh`; both are glibc builds, which Wolfi is.
- PhotoPrism links libvips via cgo; today it builds against Ubuntu's in
  `photoprism/develop:resolute`. It must build against Wolfi's to run on the base.
- ImageMagick's policy: the current image copies `scripts/convert/policy.xml` into
  `/etc/ImageMagick-7/`; the new image needs the same policy.
- `heif-dec` is preferred by PhotoPrism (`HeifConvertBin` → `heif-dec`, `heif-convert`);
  the repo's `heif-convert.sh` wrapper is not used.
- The fork's local branch is 9 commits ahead of `private/k8s-parallel-index`. The Go
  rewrite reproduces the **local branch's** behaviour (skip-library-update, third-level
  walking, `.heic` renames, cross-partition stealing, large-first pod start order);
  push those commits first. (Builder's call, made in design.)
- Deploy through Fleet/GitOps or the maintenance repo's own deploy, never ad-hoc helm.

## Left to the builder

- How to unpack and run the AppImages without `AppRun` (e.g. extract the squashfs at
  package build time, run the ELF with an `RPATH`/`LD_LIBRARY_PATH` set via a tiny
  static launcher, or relink).
- Whether darktable/RawTherapee need their data dirs (`share/darktable`, profiles,
  lensfun DB) relocated, and `HOME`/config dirs for the non-interactive CLIs.
- Exact Wolfi build image and the Dockerfile for the fork (`docker/photoprism/wolfi/`
  or similar), and how the frontend build gets node.
- The catalog shape for `photoprism-base` (single line `latest`, or versioned on
  darktable/RawTherapee).
- How the format smoke-test fixtures are sourced (small sample files committed or
  downloaded by checksum).
