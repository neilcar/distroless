# Distroless PhotoPrism Index Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the PhotoPrism parallel index Jobs on a shell-free image built from a new
`photoprism-base` distroless image, with the bash pod scripts replaced by a Go program.

**Architecture:** `neilcar/distroless` gains a `photoprism-base` image: the Wolfi part built
by apko like the other images, plus one appended "vendor layer" holding darktable,
RawTherapee and yt-dlp from pinned upstream release files. The fork gains `parallel-index`
(Go, stdlib only) on `k8s-parallel-index`. The `k8s-261007-skip-fixes` branch builds
PhotoPrism 261007 on the base's `-dev` variant, adds `parallel-index` at a pinned commit,
and publishes `ghcr.io/neilcar/photoprism-index`. The maintenance driver switches the Jobs.

**Tech Stack:** apko 1.4.13, crane 0.22.1, Trivy 0.76.1, cosign v3 (existing
`setup-tools` action), Python 3 + uv + pytest (`dltools`), Go (stdlib), squashfs-tools,
GitHub Actions native amd64/arm64 runners, bash `test.sh` as the black-box suite.

**Spec:** `docs/superpowers/specs/2026-10-24-photoprism-index-design.md` (approved 2026-10-24)

## Repos and branches

| Repo (local path) | Base branch | Work branch | Lands by |
|---|---|---|---|
| `neilcar/distroless` (`~/code/home/distroless`) | `main` | `photoprism-base` | PR, merge |
| `neilcar/photoprism-k8s` (`~/code/home/photoprism`, remote `private`) | `k8s-parallel-index` | `parallel-index-go` | PR into `k8s-parallel-index` |
| `neilcar/photoprism-k8s` (`~/code/home/photoprism-261007`, a worktree) | `k8s-261007-skip-fixes` | `wolfi-image` | PR into `k8s-261007-skip-fixes` |
| `~/code/home/photoprism-maintenance` (local git, no remote) | — | commits on its branch | `deploy.sh`, `kubectl apply -f trigger.yaml` |

## Global Constraints

- Released versions only: darktable **5.6.2**, RawTherapee **5.13**, yt-dlp pinned to a
  release tag (today `2026.10.21`). No `_rc`/`_git`/nightly/debug builds; each upstream file is pinned by sha256.
- Both `linux/amd64` and `linux/arm64`. Wolfi arch names `x86_64`, `aarch64`.
- The runtime image has **no shell** (`sh`, `bash`, `ash`, `busybox`) and no `apk`. The `-dev` variant may have them.
- `photoprism-base` and `photoprism-index` run as **uid/gid 0** (owner's decision); every other image keeps 65532.
- The parallel-index behaviour reference is the scripts at the **head of `k8s-parallel-index` when Task 6 starts** (today `17ea6a25b`); later script changes must be mirrored in Go, enforced by `difftest.sh` in CI. Settings, defaults, output lines, plan files, claim layout and exit codes (0, 1, 3, 4, 5) are byte-for-byte compatible.
- PhotoPrism stays release **261007** with the `k8s-261007-skip-fixes` patches (schema must match the server).
- Image names: `ghcr.io/neilcar/distroless/photoprism-base` (`latest`, `latest-dev`), `ghcr.io/neilcar/photoprism-index`. `ghcr.io/neilcar/photoprism-k8s` keeps publishing unchanged.
- Trivy rule: the switch happens only if C/H/M/L is lower than `photoprism-k8s` at digest `sha256:df9bd936e056c024fc5f0884325553733c13a66bfffd3fea44fbfc00eb4ef10a`, counting only non-vendored findings. Vendored findings (under `/opt/darktable`, `/opt/rawtherapee`, `/opt/yt-dlp`) are listed separately.
- Nothing pushes to `main`, `k8s-parallel-index` or `k8s-261007-skip-fixes` without the owner's OK; the cluster changes only in Task 13.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings made while planning (deviations from the spec's wording)

1. **Vendor layer, not melange packages.** The AppImages are 122–178 MB; GitHub rejects files over 100 MB, so they cannot be committed under `packages/` like `distroless-nginx-config`. They are downloaded at build time (sha256-pinned), unpacked, and appended to the apko image as one deterministic layer. yt-dlp uses the same mechanism (its standalone `yt-dlp_linux`/`yt-dlp_linux_aarch64` release binaries). Cost if wrong: the base has one non-apk layer whose SBOM entries come from the vendor manifest instead of apko.
2. **`test.sh` stays as the black-box suite**, pointed at the Go binary, instead of being rewritten in Go. It already encodes the behaviour (92 checks passed on Linux at `a6eb4ab08`; recount at the branch point); Go unit tests cover the internals. A differential test compares the bash and Go plans directly until the scripts are deleted. Cost if wrong: the suite still needs bash on the CI runner (never in the image).
3. **The image is built on `k8s-261007-skip-fixes`**, not `k8s-parallel-index`: the current index image (tag `k8s-261007-4`) is built there, and the server is 261007. `parallel-index` comes from `k8s-parallel-index` at a commit pinned in `docker/photoprism/wolfi/PARALLEL_INDEX_REF`.
4. **The RawTherapee fallback is exercised by disabling darktable** (`PHOTOPRISM_DISABLE_DARKTABLE=true`) on a RAW fixture, rather than by finding a RAW darktable cannot decode.

## Review Focus

1. Folder names with spaces, non-ASCII characters, a leading `-`, or a newline: claims (sha1 of the folder path, as `printf '%s' | sha1sum`) and `photoprism` arguments must match bash exactly and never be parsed as flags. Test in Task 8.
2. `mkdir` on the claims folder failing for a reason other than "already exists" (ENOENT, EACCES, EIO on NFS): only EEXIST means "taken"; anything else is a failed folder, not a skipped one. Test in Task 8.
3. A `photoprism` child killed by SIGKILL (the OOM killer): it must produce the `OOM<TAB>folder` line and exit 5, the same as bash. A SIGTERM to `parallel-index` (pod deletion) must reach the child and not leave it orphaned. Test in Task 8.
4. cgroup v1 vs v2, `memory.max` = `max`, and a missing downward-API `MEMORY_LIMIT`: same limit and worker count as bash, and exit 3 where bash exits 3. Test in Task 6.
5. `exiftool` missing, failing, or printing non-numbers: the folder counts as large, the plan doesn't abort, and the log says so as bash does. Test in Task 7.

---

## Part 1 — `photoprism-base` (repo `distroless`, branch `photoprism-base`)

### Task 1: Catalog support for per-image user and vendored files

**Files:**
- Modify: `src/dltools/render.py`, `src/dltools/lines.py`, `src/dltools/cli.py` (sync writes `vendor.json`)
- Modify: `catalog.yaml`
- Test: `tests/test_render.py`, `tests/test_lines.py`, `tests/test_cli_sync.py`

**Interfaces:**
- Produces: catalog keys `images.<name>.run_as` (string uid, overrides `accounts.run-as`) and `images.<name>.vendor` (a list of `{name, version, kind: appimage|binary, prefix, files: {x86_64: {url, sha256}, aarch64: {url, sha256}}, launchers: [...]}`).
- Produces: `render(catalog, line, variant) -> dict` sets `accounts.run-as` from `run_as`; `render_vendor(catalog, line) -> dict | None` returns `{"vendor": [...]}`. `dl sync` writes it to `locks/<image>/<line>/vendor.json` (sorted keys, trailing newline), so a version bump changes the line's lock dir and triggers its build.
- Produces: `photoprism_base_lines(indexes) -> list[Line]`: one line `Line("photoprism-base", "latest", <Wolfi libvips package>, <newest released>)`, ordered after nginx in `_order`.

- [ ] **Step 1: Write the failing tests**
  - `test_render_run_as_override`: a catalog image with `run_as: "0"` renders `accounts["run-as"] == "0"`; an image without it keeps `"65532"`.
  - `test_render_vendor_written_per_line`: `render_vendor` returns the image's `vendor` list unchanged; it returns `None` for an image without `vendor`.
  - `test_photoprism_base_line`: an index fixture with the libvips package at `8.18.7-r0` and a `-r1` `_rc` build yields one `latest` line at the released version.
  - `test_sync_writes_vendor_json`: after `dl sync` against fixtures, `locks/photoprism-base/latest/vendor.json` exists and a second sync leaves it byte-identical.
- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/test_render.py tests/test_lines.py tests/test_cli_sync.py -q`. Expected: the 4 new tests FAIL (KeyError / missing function).
- [ ] **Step 3: Implement** the three functions, and the sync change. Confirm the Wolfi package name for libvips with `uv run dl fetch-index` plus a grep. Use the package that ships `libvips.so.42`.
- [ ] **Step 4: Add the catalog entry**:
  - `photoprism-base`: `run_as: "0"` and `lines: [latest]`.
  - `runtime` variant packages: `ffmpeg`, `exiftool`, `perl`, `libheif`, `libheif-tools` (or the package that ships `heif-dec`/`heif-enc`), `imagemagick`, the libvips package and its tools (`vips`), `libjxl-tools`, `ghostscript`, `librsvg` (`rsvg-convert`), `mariadb-11.8-client`, `sqlite`, the ffmpeg codec libraries if not pulled in by ffmpeg (x265, dav1d, aom, libde265, libva), `glibc-locale-posix`, `libstdc++`, `fontconfig`, `font-dejavu`.
  - `dev` variant: the runtime packages plus `busybox`, `bash`, `curl`, `git`, `make`, `go`, `nodejs-22`, `npm`, `gcc`, `glibc-dev`, the libvips `-dev` package, `libheif-dev`, `pkgconf`.
  - `paths`: `/tmp` 01777.
  - `vendor`: darktable 5.6.2 (`appimage`, prefix `/opt/darktable`, launcher `darktable-cli`), RawTherapee 5.13 (`appimage`, prefix `/opt/rawtherapee`, launcher `rawtherapee-cli`) and yt-dlp (`binary`, prefix `/opt/yt-dlp`, launcher `yt-dlp`).
  - The sha256 values come from the release files, computed by downloading each once. Every package name must resolve in `apko lock` on both arches. Run `.github/scripts/lock-all.sh` locally with `RUNNER_TEMP` set.
- [ ] **Step 5: Verify.** Run: `uv run pytest -q`. Expected: all pass (115 + 4).
- [ ] **Step 6: Commit** — `feat: photoprism-base catalog entry with run_as and vendored files`.

### Task 2: The vendor layer (`dl vendor-layer`, `dl append-layer`)

**Files:**
- Create: `src/dltools/vendor.py`, `src/dltools/ocilayout.py`
- Modify: `src/dltools/cli.py`
- Test: `tests/test_vendor.py`, `tests/test_ocilayout.py`, fixtures under `tests/fixtures/vendor/`

**Interfaces:**
- Consumes: `vendor.json` from Task 1.
- Produces:
  - `appimage_offset(path) -> int`: the end of the ELF runtime, `e_shoff + e_shentsize * e_shnum`. It checks that the bytes at the offset are the squashfs magic `hsqs`, and raises `ValueError` otherwise.
  - `build_layer(vendor: dict, arch: str, cache_dir: Path, out: Path, launcher_bin: Path) -> dict`: the result is a deterministic `.tar.gz` with sorted entries, mtime 0, uid/gid 0, gzip mtime 0, and no extended attributes.
    - It downloads each file to `cache_dir` and checks its sha256, raising on a mismatch before anything is unpacked.
    - It unpacks AppImages with `unsquashfs -no-xattrs -o <offset>` into `<prefix>/`, and copies `binary` files to `<prefix>/<launcher>` with mode 0755.
    - It installs `launcher_bin` as `/usr/bin/<launcher>` for each launcher, together with `<prefix>/launch.json` (from Task 3).
    - It returns a manifest `{name, version, arch, url, sha256}` per file.
  - `append_layer(layout: Path, arch: str, layer: Path, history: str) -> None`: adds the blob to `layout/blobs/sha256/` for the manifest of `arch`. It updates that image's config (`rootfs.diff_ids`, `history`), the manifest (layers, config digest) and the index entry (digest, size), and leaves other arches untouched.
  - CLI: `dl vendor-layer --vendor <vendor.json> --arch <arch> --launcher <bin> --cache <dir> --out <tar.gz> --manifest <json>` and `dl append-layer --layout oci/ --arch <arch> --layer <tar.gz>`.

- [ ] **Step 1: Write the failing tests**
  - `test_appimage_offset_finds_squashfs`: the fixture is a small static ELF from `tests/smoke/hello.go`, built in the test session fixture, concatenated with a `mksquashfs` image of a two-file dir. The offset equals the ELF size, and `hsqs` is found there.
  - `test_appimage_offset_rejects_plain_elf` raises `ValueError`.
  - `test_build_layer_is_deterministic`: two builds from the same cached inputs give byte-identical tarballs, and every member has `mtime == 0`, `uid == gid == 0`, in sorted order.
  - `test_build_layer_rejects_bad_sha256`: raises before writing `out`.
  - `test_build_layer_installs_launchers`: `usr/bin/darktable-cli` is the launcher binary, and `opt/darktable/launch.json` exists.
  - `test_append_layer_updates_one_arch`: on a two-arch fixture layout made by `apko build` of `static` (session fixture, skipped if apko is absent), the amd64 manifest gains one layer whose digest matches the blob. The config's `diff_ids` gains the uncompressed sha256, and the arm64 manifest digest is unchanged. `crane validate --oci-layout`-equivalent checks pass (`crane config`/`crane manifest` on the layout).
- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/test_vendor.py tests/test_ocilayout.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `vendor.py`, `ocilayout.py` and the CLI subcommands** with the stdlib (`tarfile`, `gzip`, `hashlib`, `json`, `urllib.request`), shelling out only to `unsquashfs`.
- [ ] **Step 4: Verify.** Run: `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** — `feat: vendor layer for files that are not Wolfi packages`.

### Task 3: AppImage launch recipes and the launcher

The AppImages' `AppRun` launchers are shell scripts or need a shell, so they can't be used. The launcher replaces them.

**Files:**
- Create: `launcher/go.mod` (module `github.com/neilcar/distroless/launcher`, stdlib only), `launcher/main.go`, `launcher/main_test.go`
- Create: `vendor/darktable/launch.json`, `vendor/rawtherapee/launch.json`, `vendor/yt-dlp/launch.json` (`build_layer` copies them into `<prefix>/launch.json`)
- Modify: `.github/actions/setup-tools/action.yml` (install `squashfs-tools` and Go)

**Interfaces:**
- Produces the `launch.json` schema: `{"exec": "<path under prefix>", "loader": "<ld.so under prefix, optional>", "library_path": ["<dirs under prefix>"], "env": {"K": "V with ${PREFIX}"}, "env_default": {"HOME": "/tmp"}}`.
- The launcher resolves `/opt/<tool>` from `basename(argv[0])` with a map compiled in, `{"darktable-cli": "/opt/darktable", "rawtherapee-cli": "/opt/rawtherapee", "yt-dlp": "/opt/yt-dlp"}`. It reads `launch.json` and then `syscall.Exec`s. With `loader` set, it runs `loader --library-path <joined> <exec> args...`; without it, it sets `LD_LIBRARY_PATH` and runs `exec args...`. The caller's environment is kept, `env` is applied over it, and `env_default` only fills unset variables.

- [ ] **Step 1: Find the recipe** for each AppImage on both arches. Unpack each one with `dl vendor-layer`'s extractor, then read its `AppRun` and the `.env`/`apprun-hooks` files to collect the variables it sets: `LD_LIBRARY_PATH`, `GDK_PIXBUF_MODULE_FILE`, `XDG_DATA_DIRS`, darktable's `DARKTABLE_*`/datadir, and whether a bundled `ld-linux` is used. Write the three `launch.json` files. Record the findings, one paragraph per tool, in the ledger.
- [ ] **Step 2: Write the failing tests** in `launcher/main_test.go`:
  - `TestLauncherExecsWithLibraryPath`: with a temp prefix, a stub `exec` (a test helper binary that prints `os.Args` and `LD_LIBRARY_PATH`) and `env_default HOME=/tmp`, the output shows the args passed through unchanged (including one with a space) and `LD_LIBRARY_PATH` set to the joined dirs.
  - `TestLauncherUsesLoader`: with `loader` set, the argv starts with `<loader> --library-path <dirs> <exec>`.
  - `TestLauncherKeepsCallerEnv`: a caller `HOME=/x` survives `env_default`.
  - `TestLauncherUnknownName`: exit 127 with `launcher: no tool for <name>` on stderr.
- [ ] **Step 3: Run them to see them fail.** Run: `cd launcher && go test ./...`. Expected: FAIL.
- [ ] **Step 4: Implement `main.go`.** Build it with `CGO_ENABLED=0 go build -trimpath -ldflags=-buildid=` per arch, so builds are reproducible.
- [ ] **Step 5: Verify on real binaries.** On an amd64 host, and in an arm64 runner in Task 4's CI, run `darktable-cli --version` and `rawtherapee-cli -v` through the launcher, inside a `photoprism-base` candidate container with no shell. Expected: version strings `5.6.2` and `5.13`.
- [ ] **Step 6: Commit** — `feat: launcher that runs vendored AppImage binaries without AppRun`.

### Task 4: Build, smoke test and gate `photoprism-base`

**Files:**
- Modify: `.github/workflows/build.yml` (vendor and append steps), `tests/smoke/test_images.sh` (a `photoprism-base` case), `src/dltools/gate.py` (vendored findings become notes), `README.md` (Images table)
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `dl vendor-layer`, `dl append-layer` and the launcher (Tasks 2–3).
- Produces: `evaluate(..., vendor_prefixes: list[str])`. A finding whose `PkgPath`/`Target` starts with a vendored prefix, or that comes from a vendored file's SBOM component, is reported under a new `vendored` section of the summary. It doesn't count toward fixable-High blocking or the not-worse rule. The CLI flag is `dl gate --vendor-prefix /opt/darktable --vendor-prefix ...`, derived in `build.yml` from `vendor.json`.

- [ ] **Step 1: Write the failing tests**
  - `test_gate_vendored_findings_are_notes`: a candidate report with one High under `opt/darktable/usr/lib/libexiv2.so` with an available fix passes the gate. The summary markdown lists it under `Vendored (not gated)`.
  - `test_gate_vendored_not_counted_in_regression`: two extra vendored Mediums don't trip the not-worse rule.
- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/test_gate.py -q`. Expected: the 2 new tests FAIL.
- [ ] **Step 3: Implement the gate change.** In `build.yml`, for a line dir that contains `vendor.json`:
  - build the launcher for both arches, then run `dl vendor-layer` per arch (cache the downloads with `actions/cache`, keyed on the `vendor.json` hash);
  - run `dl append-layer` on `oci/` *before* the per-arch views, the scan and the push, so the scanned digest is the pushed digest;
  - also append the layer to the docker tarball used by the smoke test.
  - The revision annotation logic is unchanged, because `vendor.json` sits in the lock dir.
- [ ] **Step 4: Smoke test case `photoprism-base`.** The user check accepts `0`/`root` for this image only. The runtime image must have no shell and no apk, as for the others. Each of these runs with `--entrypoint` and exits 0:
  - `ffmpeg -version`, `exiftool -ver`, `heif-dec --version`, `magick -version`, `vips --version`, `djxl --version`
  - `rsvg-convert --version`, `mariadb --version`, `gs --version`
  - `darktable-cli --version` (output contains `5.6.2`), `rawtherapee-cli -v` (contains `5.13`), `yt-dlp --version`
  - `-dev` only: `go version`, `node --version`, `make --version`, `bash --version`.
- [ ] **Step 5: Verify.** Run `uv run pytest -q`, then push the branch and dispatch `build.yml` for `photoprism-base`. Expected: tests pass, and the build is green on both arches with the smoke test passing. The gate summary shows the counts for the Wolfi part and a vendored section, and the candidates are pushed and signed. Copy the gate summary into the ledger.
- [ ] **Step 6: Commit** — `feat: build, smoke test and gate photoprism-base`.

### Task 5: Release watcher for vendored tools

**Files:**
- Create: `src/dltools/vendorcheck.py`
- Modify: `src/dltools/cli.py`, `.github/workflows/rescan.yml`
- Test: `tests/test_vendorcheck.py`

**Interfaces:**
- Produces: `newer_releases(vendor: dict, releases: dict[str, list[dict]]) -> list[str]`, which returns one message per tool whose newest *stable* GitHub release is newer than its pinned version. Stable means not a draft, not a prerelease, and with no `rc`/`beta`/`alpha`/`dev`/`nightly` in the tag.
  - Tag normalisation: darktable `release-X.Y.Z` → `X.Y.Z`, RawTherapee `X.Y` as is, yt-dlp `YYYY.MM.DD`.
- Produces: `dl vendor-check --vendor <vendor.json>`, which fetches releases with `GH_TOKEN`. When there are messages, it opens or updates one `automation` issue, `Vendored tool updates available` (via `notify.py`), and exits 0. On a network failure it warns, and the job doesn't fail.
- Repos: `darktable-org/darktable`, `RawTherapee/RawTherapee`, `yt-dlp/yt-dlp`.

- [ ] **Step 1: Write the failing tests**:
  - `test_newer_stable_release_reported`: pinned 5.6.2, releases `release-5.6.3` and `release-5.8.0rc1` → one message naming 5.6.3.
  - `test_prerelease_and_draft_ignored`.
  - `test_same_version_no_message`.
  - `test_yt_dlp_date_versions_compare`: `2026.10.21` < `2026.11.02`.
- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/test_vendorcheck.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**, and add a `vendor-check` step to `rescan.yml` after the rescan.
- [ ] **Step 4: Verify.** Run `uv run pytest -q`, then `uv run dl vendor-check --vendor locks/photoprism-base/latest/vendor.json --dry-run`. Expected: all pass, and the dry run prints `no newer releases` (or the real ones).
- [ ] **Step 5: Commit** — `feat: open an issue when vendored tools have new releases`. Open the PR for Part 1. Merge it only with the owner's OK, then confirm `photoprism-base:latest` and `:latest-dev` are published and signed.

## Part 2 — `parallel-index` (repo `photoprism`, branch `parallel-index-go`)

Before starting, ask the owner to push the 10 local commits on `k8s-parallel-index` to `private`, or to OK you pushing them. Then branch from the head of `k8s-parallel-index`, which was `17ea6a25b` when this was written.

### Task 6: Implementation-agnostic test suite, module skeleton and resources

**Files:**
- Modify: `setup/kubernetes/parallel-index/test.sh`: `PLAN_CMD` (default `bash $DIR/scripts/plan.sh`) and `INDEX_CMD` (default `bash $DIR/scripts/index.sh`) replace every direct `bash "$DIR/scripts/…"` call; nothing else changes.
- Create: `setup/kubernetes/parallel-index/go.mod` (module `github.com/neilcar/photoprism-k8s/parallel-index`, `go 1.25`, no dependencies), `cmd/parallel-index/main.go`, `internal/settings/settings.go`, `internal/resources/resources.go` and their `_test.go` files.
- Create: `setup/kubernetes/parallel-index/ci.sh`, which runs the suite in `docker run --rm -v …:/src -w /src ubuntu:24.04` with GNU tools, `exiftool` stubbed as `test.sh` does, so it can also run on macOS. It's used locally only; CI runs `test.sh` directly on ubuntu.

**Interfaces:**
- Produces:
  - `settings.Int(name string, def int) int`, `settings.String(name, def string) string`, `settings.Bool(name string, def bool) bool` and `settings.Auto(name string) (n int, auto bool)`. Each matches the bash defaulting `${X:-default}`: an empty value means the default.
  - `resources.CgroupLimit(root string) (bytes int64, ok bool)`, which reads `memory.max`, then `memory/memory.limit_in_bytes`, and ignores values ≥ 4611686018427387904 and `max`.
  - `resources.WorkingSet(root string) (int64, error)`: the same formula as `index.sh` `working_set()`.
  - `resources.Workers(limitBytes int64, cpus float64, baseMB, workerMB, maxWorkers int) int`, which is `min(cpu, (limit-base)/worker, max)`.
  - `main` dispatches `plan` and `index`. Anything else gets usage on stderr and exit 2.

- [ ] **Step 1: Baseline.** Run: `bash setup/kubernetes/parallel-index/ci.sh`. Expected: `92` ok lines and `0 test(s) failed`. If not, stop: the reference itself is broken.
- [ ] **Step 2: Write the failing Go tests:**
  - `TestCgroupLimitV2`, `TestCgroupLimitV1`, `TestCgroupLimitMax` (`max` → not ok), `TestCgroupLimitHuge` (`9223372036854771712` → not ok).
  - `TestWorkers`: 8 GiB / 3 CPU / base 1500 / worker 2000 → 3; 6 GiB → 2; with max 1 → 1; 1 GiB → 0.
  - `TestWorkingSet`: on a fixture `memory.current`/`memory.stat`, the result equals the bash function's output on the same fixture. The test runs `index.sh`'s function through `bash -c` and skips if bash is absent.
- [ ] **Step 3: Run them to see them fail.** Run: `cd setup/kubernetes/parallel-index && go test ./...`. Expected: FAIL (undefined).
- [ ] **Step 4: Implement** the settings and resources packages and the `main` dispatch.
- [ ] **Step 5: Verify.** Run `go test ./...` and `bash ci.sh`. Expected: go tests pass; `ci.sh` still has 92 ok and 0 failed with the default commands.
- [ ] **Step 6: Commit** — `Kubernetes: Run the parallel index tests against any plan and index command`.

### Task 7: `parallel-index plan`

**Files:**
- Create: `internal/plan/scan.go` (port of `plan.sh` lines 106–181: the walk, the skipped folders, `SCAN_JOBS` concurrency and `scanning:` progress), `internal/plan/sample.go` (lines 154–182 plus the exiftool sampling and `sampling:` progress), `internal/plan/plan.go` (the awk program from line 183 to the end: weights, classes, splits, budget, placement and output), and their `_test.go` files
- Create: `setup/kubernetes/parallel-index/difftest.sh`

**Interfaces:**
- Consumes: `settings`, from Task 6.
- Produces: `plan.Run(env settings.Env, stdout, stderr io.Writer) int`, wired as `parallel-index plan`. stdout gets the same `PLAN`/`PLANM`/`PLANL`/`PLANX`/`PODS`/`PLACE`/`FITS` lines in the same order. stderr gets the same `plan: …` lines, with timing lines matched in tests by pattern only. The exit codes are the same.
- `difftest.sh` runs `plan.sh` and `parallel-index plan` on each library that `test.sh` generates, plus 20 seeded random libraries (seeded `$RANDOM` sizes, depths 1–4, names with spaces, `é`, a leading `-`, and RAW stubs with sidecars present or absent). It uses every settings combination `test.sh` uses (budget, nodes, `*_FITS`, `*_PARTITIONS=0`, `XL_MEGAPIXELS`) and compares stdout exactly, and stderr with timings masked.

- [ ] **Step 1: Write the failing tests:**
  - `TestClassify`: largest megapixels 30/50/90/200/unknown → small/medium/large/xl/large with the default thresholds. With `XL_FITS=false`, 200 → large.
  - `TestSplitWhenSubfolderNeedsSmallerClass`: a medium folder whose own files have previews and whose subfolder is small is split.
  - `TestExiftoolFailureCountsAsLarge` (Review Focus 5): with `EXIFTOOL` pointing to a stub that exits 1 and another that prints `abc`, the folder is large, the plan exits 0, and stderr has the same line as bash.
  - `TestPodsPlacementBestFit`: with `NODES=a:8000:20000,b:16000:64000` and a large-class folder, `PLACE<TAB>large<TAB>a` is chosen when a has room (the least left after placement).
- [ ] **Step 2: Run them to see them fail.** Run: `go test ./internal/plan/...`. Expected: FAIL.
- [ ] **Step 3: Implement**, porting the awk program function by function. Integer and float arithmetic must match awk, which uses doubles: use `float64` where awk computes and format numbers as awk's `%d`/`%.Nf` would.
- [ ] **Step 4: Verify.** First run `go test ./...`, then build and run both the suite and the differential test:

  ```bash
  go build -o /tmp/pi ./cmd/parallel-index
  PLAN_CMD="/tmp/pi plan" bash ci.sh
  bash difftest.sh /tmp/pi
  ```

  Expected: go tests pass. `ci.sh` passes every plan check (index checks still run on bash), and `difftest.sh` prints `0 differences`.
- [ ] **Step 5: Commit** — `Kubernetes: Port plan.sh to parallel-index plan`.

### Task 8: `parallel-index index`

**Files:**
- Create: `internal/index/index.go` (main loop, partition and finalize modes), `claims.go` (`claim()`/`finish()`, `TAKE_FROM`, helpers, take-back), `steps.go` (`fix_extensions`, `convert_folder`, `thumbs_folder`, `index_folder`, `--skip-library-update`, `--indexed-only`), `progress.go` (step file, `sample()`, `report()`, peak line) and their `_test.go` files

**Interfaces:**
- Consumes: `settings`, `resources`.
- Produces: `index.Run(env settings.Env, stdout, stderr io.Writer) int`, wired as `parallel-index index`. It matches `index.sh`:
  - the same environment and defaults (note `WORKER_MEM_MB` defaults to `1000` in `index.sh`);
  - the same log lines with the `date -u +%Y-%m-%dT%H:%M:%SZ` prefix, the same `OOM\t<folder>` lines and exit codes;
  - the same child commands and arguments (`photoprism index|convert|thumbs|purge|faces update`, found on `PATH`);
  - the same environment for the children (`PHOTOPRISM_INDEX_WORKERS`, `GOMAXPROCS`, `PHOTOPRISM_DATABASE_CONNS`, `MALLOC_ARENA_MAX=2`).
- Claims: `os.Mkdir(<CLAIM_DIR>/<sha1hex(folder)>)`. `errors.Is(err, fs.ErrExist)` means taken; any other error marks the folder failed (exit 1 path), matching bash's behaviour when its `mkdir` fails for another reason. Check `index.sh` lines 187–210 and keep whichever the script does.
- Signals: on SIGTERM/SIGINT, it forwards the signal to the running child, waits, and exits with the code bash's trap produces. A child that ends by SIGKILL counts as OOM.

- [ ] **Step 1: Write the failing tests:**
  - `TestClaimNamesMatchSha1sum` (Review Focus 1): for `a b`, `é/x`, `-n` and `x\ny`, the claim dir name equals `printf '%s' "$f" | sha1sum | cut -c1-40`.
  - `TestClaimOtherErrorIsFailure` (Review Focus 2): with `CLAIM_DIR` read-only, the folder is reported failed and the exit is 1, not skipped.
  - `TestFolderWithLeadingDashPassedAsPath` (Review Focus 1): a stub `photoprism` records its argv, and the folder argument arrives unchanged in the position `index.sh` uses.
  - `TestChildSigkillIsOOM` (Review Focus 3): a stub that does `kill -9 $$` on `index` → stdout has `OOM\t<folder>` and the exit is 5.
  - `TestSigtermForwardedToChild` (Review Focus 3): send SIGTERM to `parallel-index` while the stub sleeps; the stub records that it got TERM, and no child is left running.
  - `TestNoMemoryLimitExits3` (Review Focus 4): neither `MEMORY_LIMIT` nor a cgroup limit → exit 3 with the same message as bash.
- [ ] **Step 2: Run them to see them fail.** Run: `go test ./internal/index/...`. Expected: FAIL.
- [ ] **Step 3: Implement**, porting `index.sh` section by section. Use `exec.Command` with explicit argv, never a shell. Read the child's output line by line the same way the `index_folder` pipe does.
- [ ] **Step 4: Verify.**

  ```bash
  go build -o /tmp/pi ./cmd/parallel-index
  PLAN_CMD="/tmp/pi plan" INDEX_CMD="/tmp/pi index" bash ci.sh
  ```

  Expected: 92 ok, 0 failed.
- [ ] **Step 5: Commit** — `Kubernetes: Port index.sh to parallel-index index`.

### Task 9: Jobs run the binary; CI

**Files:**
- Modify: `setup/kubernetes/parallel-index/parallel-index.sh`:
  - the rendered `command` becomes `["/opt/parallel-index/bin/parallel-index", "plan"|"index"]`;
  - remove the `scripts` volume, the mount and the ConfigMap creation;
  - `INDEX_IMAGE` defaults to `ghcr.io/neilcar/photoprism-index:latest`.
- Modify: `setup/kubernetes/parallel-index/test.sh` (`pi` render checks expect the new command and no `scripts` volume), `README.md` (the binary, `INDEX_IMAGE`, and the Tests section)
- Modify: `.github/workflows/image.yml` `script-test` job:
  - `shellcheck` covers `parallel-index.sh`, `test.sh` and `difftest.sh`;
  - add `go test ./...` and `go vet ./...` in `setup/kubernetes/parallel-index`;
  - run `test.sh` with `PLAN_CMD`/`INDEX_CMD` set to the built binary, and also with the defaults;
  - run `difftest.sh`.

- [ ] **Step 1: Write the failing check.** In `test.sh`, add `expect "render: index job runs the binary"`: the rendered Job's command is `["/opt/parallel-index/bin/parallel-index","index"]`. Add `expect "render: no scripts volume"` as well.
- [ ] **Step 2: Run it to see it fail.** Run: `bash ci.sh`. Expected: those 2 FAIL.
- [ ] **Step 3: Implement** the `parallel-index.sh`, README and workflow changes.
- [ ] **Step 4: Verify.** Run `bash ci.sh` with the Go commands, then push `parallel-index-go` and open the PR into `k8s-parallel-index`. Expected: all ok locally, and the CI `Parallel index scripts` job green. Merge only with the owner's OK. Record the merge commit for `PARALLEL_INDEX_REF`.
- [ ] **Step 5: Commit** — `Kubernetes: Run parallel-index from the image instead of mounted scripts`.

## Part 3 — `photoprism-index` image (worktree `photoprism-261007`, branch `wolfi-image`)

### Task 10: Wolfi Dockerfile

**Files:**
- Create: `docker/photoprism/wolfi/Dockerfile`, `docker/photoprism/wolfi/PARALLEL_INDEX_REF` (the Task 9 merge commit)

**Interfaces:**
- Build stage: `FROM ghcr.io/neilcar/distroless/photoprism-base:latest-dev@sha256:…` with `USER root`, then `make all install DESTDIR=/opt/photoprism`. It uses the repo's `install-tensorflow.sh`/`install-onnx.sh` through `make install`, with bash and curl from `-dev`.
- `parallel-index` stage: same base. It takes the named build context `parallel-index` (the `k8s-parallel-index` checkout at `PARALLEL_INDEX_REF`) and runs `CGO_ENABLED=0 go build -trimpath -o /out/parallel-index ./cmd/parallel-index`.
- Final stage, `FROM ghcr.io/neilcar/distroless/photoprism-base:latest@sha256:…`:
  - copy `/opt/photoprism` and `/out/parallel-index` → `/opt/parallel-index/bin/parallel-index`;
  - copy `scripts/dist/convert/policy.xml` → `/etc/ImageMagick-7/policy.xml`;
  - set the `ENV` block from `docker/photoprism/resolute/Dockerfile`, dropping `DEBIAN_FRONTEND` and `PROG`, and adding `PATH=/opt/photoprism/bin:/usr/bin:/bin`;
  - `WORKDIR /photoprism`, `USER 0:0`, `ENTRYPOINT ["/opt/photoprism/bin/photoprism"]`, `CMD ["--help"]`. No `/scripts` copy: the image has no shell to run them.
  - OCI labels: title `photoprism-index`, source `https://github.com/neilcar/photoprism-k8s`, and revision.

- [ ] **Step 1: Write the failing check**, `docker/photoprism/wolfi/check.sh <image>`, run on the runner:
  - `docker run --rm --entrypoint /bin/sh <img> -c true` must fail;
  - `photoprism --version` prints `261007`;
  - `parallel-index` with no args exits 2 and prints usage;
  - `photoprism show config` lists `darktable-bin`, `rawtherapee-bin`, `ffmpeg-bin`, `exiftool-bin`, `heifconvert-bin` (or the 261007 names) as found paths, not empty;
  - `docker inspect` user is `0:0`;
  - `docker run --rm --entrypoint /opt/photoprism/bin/photoprism -e PHOTOPRISM_INDEX_WORKERS= --memory 2g <img> show config` reports `(low-memory)` index workers, as `image.yml`'s smoke test does.
- [ ] **Step 2: Run it to see it fail.** Run: `bash docker/photoprism/wolfi/check.sh photoprism-index:test`. Expected: FAIL (no such image).
- [ ] **Step 3: Write the Dockerfile.** Build locally for the host arch:

  ```bash
  docker buildx build --build-context parallel-index=<path> -f docker/photoprism/wolfi/Dockerfile -t photoprism-index:test --load .
  ```

- [ ] **Step 4: Verify.** Run: `bash docker/photoprism/wolfi/check.sh photoprism-index:test`. Expected: `all checks passed`.
- [ ] **Step 5: Commit** — `Docker: Build the parallel index image on the distroless PhotoPrism base`.

### Task 11: Format smoke test

**Files:**
- Create: `docker/photoprism/wolfi/fixtures.txt` (`<sha256>  <url>  <name>` per line), `docker/photoprism/wolfi/formats.sh <image>`

**Interfaces:**
- Fixtures, all small public samples pinned by sha256 and downloaded into a temp originals dir:
  - one RAW darktable handles (e.g. a Nikon NEF or Sony ARW from raw.pixls.us);
  - one HEIC, plus one Apple live photo pair (HEIC + MOV);
  - one JPEG XL, one 16-bit TIFF, one PSD and one MP4 (H.264) or MOV (HEVC).
- `formats.sh` runs `photoprism convert` in the image against that dir, with a temp storage and sidecar and `PHOTOPRISM_DATABASE_DRIVER=sqlite`:
  - a first run, then a second run of the RAW only with `PHOTOPRISM_DISABLE_DARKTABLE=true` and a fresh sidecar (the RawTherapee path);
  - it asserts a non-empty JPEG preview exists in the sidecar for every fixture in each run, and that the log names `rawtherapee` for the second run;
  - it fails with the fixture name for anything missing.

- [ ] **Step 1: Write `formats.sh` and `fixtures.txt`.** Run: `bash docker/photoprism/wolfi/formats.sh photoprism-k8s:<current digest>`, against the **current Ubuntu image**. Expected: all previews created. This proves the test, not the new image.
- [ ] **Step 2: Run it against the new image.** Run: `bash docker/photoprism/wolfi/formats.sh photoprism-index:test`. Expected: all previews created. Any failure is a base or launcher defect: fix it in Part 1 (new base digest) and rerun.
- [ ] **Step 3: Commit** — `Docker: Test that every media format converts in the parallel index image`.

### Task 12: CI workflow, publish and compare

**Files:**
- Create: `.github/workflows/image-wolfi.yml`

**Interfaces:**
- Triggers: push to `k8s-261007-skip-fixes`, tags `k8s-261007-wolfi-*`, PRs and dispatch.
- Steps:
  - `actions/checkout` twice, the second for `k8s-parallel-index` at `PARALLEL_INDEX_REF` into `parallel-index/`;
  - per arch on native runners (`ubuntu-24.04`, `ubuntu-24.04-arm`): build with `--build-context parallel-index=parallel-index/setup/kubernetes/parallel-index`, then run `check.sh` and `formats.sh`;
  - Trivy JSON of the candidate, split into vendored and other by path prefix, the same as the base gate;
  - push by digest, merge a multi-arch manifest as `ghcr.io/neilcar/photoprism-index`, tagged sha-short, branch and tag;
  - `cosign sign --recursive` and SBOM attestation;
  - a job summary with the C/H/M/L table for the new image (other and vendored) against `photoprism-k8s@sha256:df9bd936…`.
- Dependabot: add a `docker` entry for `docker/photoprism/wolfi`, so the base digests get bumped.

- [ ] **Step 1: Push `wolfi-image`** and open the PR into `k8s-261007-skip-fixes`. Expected: both arch builds green, `check.sh` and `formats.sh` pass on amd64 and arm64, and the summary table is posted.
- [ ] **Step 2: Check the Trivy rule.** The new image's non-vendored C/H/M/L must be lower than the Ubuntu image's in every severity that had findings. Record the table in the ledger. If it isn't lower, stop and report to the owner: the switch doesn't happen.
- [ ] **Step 3: Merge with the owner's OK**, tag `k8s-261007-wolfi-1`, and confirm the image and signature: `cosign verify ghcr.io/neilcar/photoprism-index:k8s-261007-wolfi-1 --certificate-identity-regexp '^https://github.com/neilcar/photoprism-k8s/' --certificate-oidc-issuer https://token.actions.githubusercontent.com`. Record the index digest.
- [ ] **Step 4: Commit** (the workflow commit goes with Step 1) — `CI: Build and publish the distroless parallel index image`.

## Part 4 — Cutover (cluster changes start here)

### Task 13: Switch the maintenance driver and run the comparison

**Files:**
- Modify: `~/code/home/photoprism-maintenance/driver.sh` (`INDEX_IMAGE` to `ghcr.io/neilcar/photoprism-index@<digest from Task 12>` and its comment), `deploy.sh` (drop `plan.sh`/`index.sh`), `trigger.yaml` (the start command copies only `parallel-index.sh` and `driver.sh`; nothing else in the policy changes)

- [ ] **Step 1: Baseline.** Record the last maintenance run's SUMMARY line (from n8n or the driver Job's log), and the current counts of indexed files and sidecar previews. Those are `files` rows by `file_type` and `file_missing` from the PhotoPrism database, plus a `find /photoprism/sidecar -name '*.jpg' | wc -l` count from a debug Job. Write all of them to the ledger.
- [ ] **Step 2: Pause the Stash batch Jobs** the way the memory note `photoprism-maintenance-before-stash-jobs` describes. Read it first.
- [ ] **Step 3: Deploy the driver change.** Run `kubectl apply -f trigger.yaml`, then `bash deploy.sh`. Expected: the ConfigMap `photoprism-index-driver` has only `parallel-index.sh` and `driver.sh`, and `deploy.sh` prints the fork's `k8s-parallel-index` commit after the Task 9 merge.
- [ ] **Step 4: Run maintenance.** Trigger the normal maintenance run the way the n8n workflow does. Expected: SUMMARY status `complete`, no failed partitions, and peaks reported for every pod. The index pods' image is `photoprism-index@…`, as shown by `kubectl -n photoprism get pods -l app.kubernetes.io/part-of=photoprism-index -o jsonpath='{..image}'`.
- [ ] **Step 5: Forced re-convert of one folder.** Pick a large-class folder from the plan log whose RAWs need both darktable and the RawTherapee fallback (≥ 80 MP). Run a one-off Job from the new image with the StatefulSet's volumes and security context: `photoprism convert -f <folder>`. Expected: exit 0, and a fresh preview in the sidecar for every RAW in the folder; the log shows both `darktable` and `rawtherapee` conversions.
- [ ] **Step 6: Compare** with the baseline. The run must index the same files, with the `files` counts per type equal to or higher than before (higher only for files added since). The sidecar preview count must not be lower, and the SUMMARY problems must be no worse than the baseline. Write the comparison to the ledger.
- [ ] **Step 7: Resume Stash** only after the PhotoPrism Jobs have been finished for 30 minutes.
- [ ] **Step 8: Commit** in `photoprism-maintenance`: `Run the parallel index Jobs on the distroless photoprism-index image`.

### Task 14: Remove the scripts and record results

**Files:**
- Delete (fork, new branch `parallel-index-drop-scripts` from `k8s-parallel-index`): `setup/kubernetes/parallel-index/scripts/plan.sh`, `scripts/index.sh`, `difftest.sh`
- Modify: `test.sh` (`PLAN_CMD`/`INDEX_CMD` become required, with no bash defaults), `image.yml` (drop the default-commands run and `difftest.sh`), the README Tests section
- Modify (distroless): `README.md`, which gets a `photoprism-base` row in Images and a Results row for `photoprism-index` (C/H/M/L other and vendored, against `photoprism-k8s`)

- [ ] **Step 1: Verify** `PLAN_CMD="/tmp/pi plan" INDEX_CMD="/tmp/pi index" bash ci.sh` → 92 ok, 0 failed after the deletion.
- [ ] **Step 2: Open the PRs** in the fork and in distroless. Merge each only with the owner's OK.
- [ ] **Step 3: Commit** — `Kubernetes: Remove the bash pod scripts now that the Jobs run parallel-index` and `docs: record photoprism-index results`.

**Rollback** (any time before Task 14 merges):
1. Restore `driver.sh`'s `INDEX_IMAGE` to `photoprism-k8s@sha256:df9bd936…`.
2. `git revert` the maintenance commit.
3. Run `deploy.sh` from the fork at the Task 6 branch point, which still has the scripts.
4. `kubectl apply -f trigger.yaml`.
