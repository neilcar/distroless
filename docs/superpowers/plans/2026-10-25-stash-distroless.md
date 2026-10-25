# Distroless Stash Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Stash in the home cluster on a shell-free image built from source on a new
`stash-base` distroless image, with automatic upgrade PRs, and fewer Trivy findings than
upstream v0.31.1.

**Architecture:** `neilcar/distroless` gains `stash-base` (Wolfi ffmpeg, colour-managed
libvips, Python 3.12 with the scrapers'/plugins' libraries; pure-Python wheels not in
Wolfi come in through the vendor layer) with a `-dev` variant that has Go and Node.
`neilcar/stash-image` builds Stash from an upstream release tag on `stash-base:latest-dev`,
copies it onto `stash-base:latest`, smoke-tests it (scan, live transcode, plugin, scraper),
publishes `ghcr.io/neilcar/stash`, and opens a PR on `neilcar/lxdk8s` bumping
`stash.image` in `fleet/arr/arr-values.yaml`.

**Tech Stack:** apko/melange/`dltools` (existing distroless pipeline), Docker buildx,
Go (CGO, sqlite), Node 24 + pnpm, GitHub Actions, Trivy, cosign, bash test scripts on
the runner (never in the image), Rancher Fleet.

**Spec:** `docs/superpowers/specs/2026-10-25-stash-distroless-design.md` (approved 2026-10-25)

## Repos and branches

| Repo (local path) | Base | Work branch | Lands by |
|---|---|---|---|
| `neilcar/distroless` (`~/code/home/distroless`) | `main` | `stash-base` (has the spec and this plan) | PR, owner merges |
| `neilcar/stash-image` (clone to `~/code/home/stash-image`) | `main` (README only) | `initial` | PR, owner merges |
| `neilcar/lxdk8s` (`~/code/home/lxdk8s`) | `main` | opened by CI (Task 6) | owner merges; CI promotes to `deploy` |

## Global Constraints

- Released versions only: Stash **release tags** (`vX.Y.Z`, not prereleases), Wolfi released packages, Node/pnpm/Go released versions; PyPI wheels pinned by version and sha256.
- The runtime image has **no shell** (`sh`, `bash`, `ash`, `busybox`) and no `apk`; `-dev` may.
- `stash-base` must not change `photoprism-base` (another project depends on it); sharing `distroless-libvips` and `distroless-no-shell` is fine.
- Runtime contract stays: uid/gid **1000** (the chart sets `runAsUser`/`runAsGroup: 1000`), `HOME=/config`, `STASH_CONFIG_FILE=/config/config.yml`, `STASH_PORT=9998`, `USER=stash`, probes on `/healthz`, existing volumes and database used as-is.
- Must keep working (owner's failure conditions): **live transcoding in the browser player**, the **stash-scheduler** plugin, the **Python scrapers**, the enabled plugins (PythonDepManager, date_parser, stashdb-performer-gallery, tagScenesWithPerfTags, filenameParser).
- `stash-gen` and the Alpine helper Jobs are out of scope.
- Trivy rule: no severity higher than `docker.io/stashapp/stash:v0.31.1@sha256:df744af5a0c976e2ec671052ecc1f8a9aa757fa12b8f9930b59910b7295f0da6` and the total lower, same Trivy DB.
- Image values in the chart: `stash.image.repository`, `stash.image.tag`, `stash.image.digest` (chart `arr` 0.9.0, `templates/_helpers.tpl` `arr.image`).
- Cross-repo PRs use secret `LXDK8S_PR_TOKEN` in `neilcar/stash-image` (owner-created, already set). Never print it.
- Deploy only via Fleet (PR to `lxdk8s` `main`); never `helm upgrade`. Merges and pushes to `main` of any repo need the owner's OK.
- Commit trailers: `distroless` uses `Co-Authored-By: <model> <noreply@anthropic.com>`; `stash-image` the same; `lxdk8s` follow its existing commit style.

## Review Focus

1. Running as uid 1000 with no passwd entry: Python `os.path.expanduser`, pip user installs (PythonDepManager → `/config/.local`), and Stash itself must work with `HOME=/config`. Test in Task 4.
2. Files a browser can't play directly (HEVC in MKV, MPEG-4 Part 2 in AVI, WMV): the live transcode stream must start and be decodable. Test in Task 4.
3. Plugin and scraper commands invoking `python` vs `python3`, and scripts with `#!/usr/bin/env python3` shebangs (the runtime's `/usr/bin/env` is the minimal launcher): both names must resolve. Test in Task 2 (base smoke) and Task 4.
4. Wheels: a vendored wheel that is not pure-Python (`py3-none-any`) or whose sha256 doesn't match must fail the build, not install. Test in Task 1.
5. Upgrade automation on an unchanged state: a scheduled watcher run with no new Stash release and unchanged base digests must make no commit and open no PR; an existing open lxdk8s PR is updated, not duplicated. Test in Task 6.

---

## Part 1 — `stash-base` (repo `distroless`, branch `stash-base`)

### Task 1: Vendor kind `wheel`

**Files:**
- Modify: `src/dltools/vendor.py` (new kind), `src/dltools/cli.py` if flags change
- Test: `tests/test_vendor.py`

**Interfaces:**
- Consumes: the existing `vendor.json` schema and `build_layer(...)`.
- Produces: vendor entries with `kind: wheel`, `files` keyed by arch **or** a single `any` key (pure-Python wheels are arch-independent), `prefix` = the site-packages dir (`/usr/lib/python3.12/site-packages`). `build_layer` verifies sha256, checks the wheel filename tag ends in `-py3-none-any.whl` (else `ValueError`), unzips into `<prefix>/` (wheel contents + `.dist-info`), and writes a `RECORD`-consistent install; no `launchers` for wheels.

- [ ] **Step 1: Write the failing tests:** `test_wheel_installs_into_site_packages` (a fixture wheel built in the test with `zipfile` containing `pkg/__init__.py` and `pkg-1.0.dist-info/{METADATA,WHEEL,RECORD}` → members under `usr/lib/python3.12/site-packages/`, deterministic like other kinds); `test_wheel_any_arch_key_used_for_both_arches`; `test_wheel_rejects_platform_wheel` (`…-cp312-cp312-manylinux_2_17_x86_64.whl` → `ValueError`); `test_wheel_rejects_bad_sha256`.
- [ ] **Step 2: Run them to see them fail.** `uv run pytest tests/test_vendor.py -q` → the 4 FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.** `uv run pytest -q` → all pass.
- [ ] **Step 5: Commit** — `feat: vendor pure-Python wheels`.

### Task 2: `stash-base` image

**Files:**
- Modify: `catalog.yaml` (new image `stash-base`), `src/dltools/lines.py` (its line), `tests/smoke/test_images.sh` (a `stash-base` case), `README.md` (Images table)
- Test: `tests/test_lines.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `vendor` kinds (`wheel` from Task 1), `distroless-libvips`, `distroless-no-shell`, the existing `run_as`/`paths` catalog fields.
- Produces: `ghcr.io/neilcar/distroless/stash-base:latest` and `:latest-dev` (amd64+arm64). Line `latest`, headline package `python-3.12`. Runtime runs as **1000** (`run_as: "1000"`, account `stash` uid/gid 1000 added for this image only, home `/config`).

- [ ] **Step 1: Audit the Python imports** the image must satisfy: copy (read-only, `kubectl -n apps exec deploy/stash-app -- tar -C /config -c plugins scrapers | tar -x -C <scratch>`) the installed plugins and scrapers, and list the top-level imports of the enabled Python plugins (`stash-scheduler`, `PythonDepManager`, `date_parser`, `stashdb-performer-gallery`, `tagScenesWithPerfTags`) and of every Python scraper (`grep -l python scrapers/community/*/*.yml` → their `.py` and `py_common`). Map each import to a Wolfi `py3.12-*` package or a pure-Python PyPI wheel; anything only available as a compiled wheel and not in Wolfi → stop and report. Also grep the enabled plugins and Python scrapers for `os.system`, `shell=True`, `os.popen`, `subprocess` calls of external tools; if an enabled one needs a shell or a tool the image won't have, stop and report (spec: ask the owner). Write the result (import → package table, shell findings) to the ledger.
- [ ] **Step 2: Write the failing tests:** `test_stash_base_line` (one `latest` line headed by `python-3.12` at its newest released version); `test_render_stash_base_runtime` (packages include `ffmpeg`, `distroless-libvips`, `python-3.12`, `py3.12-requests`, `py3.12-requests-toolbelt`, `py3.12-lxml`, `py3.12-beautifulsoup4`, `py3.12-pip`, the Step 1 additions; `accounts.run-as == "1000"`; a `paths` symlink `/usr/bin/python → python3.12`; vendor wheels `cloudscraper`, `mechanicalsoup`, `stashapi` plus Step 1 additions); `test_render_stash_base_dev` (runtime packages plus `busybox`, `bash`, `go-1.27` (or the current Wolfi Go ≥ Stash's `go.mod` 1.24.3), `nodejs-24`, `npm`, `make`, `git`, `gcc`, `glibc-dev`, `coreutils`).
- [ ] **Step 3: Run them to see them fail.** `uv run pytest tests/test_lines.py tests/test_render.py -q` → FAIL.
- [ ] **Step 4: Implement** the line, the catalog entry, and any `render` support the symlink path or second account needs.
- [ ] **Step 5: Smoke case `stash-base`** in `tests/smoke/test_images.sh`: user `1000`; no shell/apk (runtime); `ffmpeg -hide_banner -encoders` lists `libx264`, `libx265`, `libvpx`, `libvpx-vp9`, `libopus`, `aac`, `libwebp`, and `-decoders` lists `hevc`, `h264`, `vp9`, `av1`, `mpeg4`, `wmv2`; `ffprobe -version`; `vips -l` lists `icc_transform` and `vipsthumbnail --version` runs; `python` and `python3` each import `requests, requests_toolbelt, lxml, bs4, cloudscraper, mechanicalsoup, stashapi` plus Step 1 additions; `python -m pip --version`; a `#!/usr/bin/env python3` script runs through the env launcher; shebang audit (existing) passes; dev: `go version` ≥ 1.24.3, `node --version` ≥ 24, `make`, `gcc`.
- [ ] **Step 6: Lock locally** (scratch clone, the loop in `.github/scripts/lock-all.sh`) — runtime and dev pass `dl lock-check` (runtime `--runtime`); then push `stash-base` and run `sync.yml`/`build.yml` on the branch (`gh workflow run … --ref stash-base`) until green on both arches. Expected: gate PASS, smoke ok.
- [ ] **Step 7: Commit** — `feat: stash-base image`. Open the PR into `main`; merge only with the owner's OK; confirm `stash-base:latest` and `:latest-dev` are published and record both digests in the ledger.

## Part 2 — `neilcar/stash-image`

### Task 3: Build Stash from source

**Files:**
- Create: `Dockerfile`, `STASH_VERSION` (`v0.31.1`), `STASH_COMMIT` (the tag's commit SHA), `README.md`, `.gitignore`

**Interfaces:**
- Consumes: `stash-base:latest-dev@sha256:…` and `stash-base:latest@sha256:…` (Task 2 digests).
- Produces: image `stash:test` locally; binary at `/usr/bin/stash`; `ENTRYPOINT ["/usr/bin/stash"]`; `USER 1000:1000`; `WORKDIR /config`; `ENV STASH_CONFIG_FILE=/config/config.yml HOME=/config STASH_PORT=9998`; `EXPOSE 9998`; OCI labels (source `https://github.com/neilcar/stash-image`, version, revision = `STASH_COMMIT`).
- Build stages (all on `stash-base:latest-dev`): `source` — `git clone --depth 1 --branch $STASH_VERSION https://github.com/stashapp/stash` and assert `git rev-parse HEAD == $STASH_COMMIT`; `frontend` — `npm install -g pnpm@<the version in ui/v2.5/package.json packageManager>`, `make pre-ui generate-ui`, `STASH_VERSION=… GITHASH=… make ui-only`; `backend` — `make generate-backend generate-login-locale`, `make flags-release flags-pie stash` with `CGO_ENABLED=1`. Final: `stash-base:latest` + the binary.

- [ ] **Step 1: Write the failing check** `tests/check.sh <image>`: no shell (`/bin/sh`, `/bin/bash`, `/usr/bin/bash`, `/bin/ash`, `/bin/busybox` each fail with "no such file"/"executable file not found", not a docker error); `stash --version` contains `v0.31.1` and the `STASH_COMMIT` short hash; `docker inspect` user `1000:1000`; the binary's Go version (`go version -m` via the dev image on an extracted copy) is the dev image's Go, not 1.24.3; `ldd`-equivalent with the runtime's loader shows no missing libraries. Each failing check prints `FAIL <name>`.
- [ ] **Step 2: Run it to see it fail.** `bash tests/check.sh stash:test` → FAIL (no image).
- [ ] **Step 3: Write the Dockerfile**; `docker buildx build -t stash:test --load .` (host arch).
- [ ] **Step 4: Verify.** `bash tests/check.sh stash:test` → `all checks passed`.
- [ ] **Step 5: Commit** on `initial` — `Build Stash from source on stash-base`.

### Task 4: Smoke tests: scan, live transcode, plugin, scraper

**Files:**
- Create: `tests/smoke.sh <image>`, `tests/fixtures/plugin/` (a tiny Python plugin `smoke_plugin.yml` + `smoke_plugin.py` using `stashapi` and the libraries), `tests/fixtures/scraper/` (a Python scraper `.yml` + `.py` that parses a fixture HTML page with `lxml`/`bs4` via `requests`), `tests/fixtures/page.html`

**Interfaces:**
- Consumes: `stash:test` (Task 3).
- `smoke.sh` runs everything from the runner: generates clips with the image's own `ffmpeg` (`--entrypoint /usr/bin/ffmpeg`): `h264.mp4` (H.264/AAC, browser-direct), `hevc.mkv` (HEVC/AAC), `mpeg4.avi` (MPEG-4 Part 2/MP3), `wmv.wmv` (WMV2/WMA), 5 s each, `testsrc2`; starts the container as uid 1000 with a temp `/config` (fresh `config.yml` with no auth, `plugins_path`/`scrapers_path` pointing at the fixture copies) and `/library`; waits for `/healthz`; via GraphQL: `configureGeneral` stash path `/library`, `metadataScan`, polls `jobQueue` until done, asserts 4 scenes; for each non-H.264 scene requests the live transcode stream (`/scene/<id>/stream.mp4` or `.webm`, whichever Stash v0.31.1 serves for transcode) for 3 s and pipes it to the image's `ffprobe` on the runner via `docker run -i` → asserts a decodable video stream; runs the fixture plugin task (`runPluginTask`) and asserts its log line and that it wrote a `pip --user` install under `/config/.local` (Review Focus 1); serves `page.html` from a local HTTP server on the docker network and runs `scrapeSingleScene` with the fixture scraper → asserts the scraped title; asserts the fixture plugin runs whether its `exec` says `python` or `python3` (two plugin yml variants) (Review Focus 3).

- [ ] **Step 1: Write `smoke.sh` and fixtures.** Run against the upstream image first (`docker.io/stashapp/stash:v0.31.1@sha256:df744af5…`, with `--entrypoint` and env adjusted for its layout) → passes. This proves the test, not the new image.
- [ ] **Step 2: Run it against the new image.** `bash tests/smoke.sh stash:test` → passes. A failure is a base or build defect: fix in Task 2/3 and rerun.
- [ ] **Step 3: Commit** — `Smoke-test scan, live transcoding, plugins and scrapers`.

### Task 5: CI build, compare, publish

**Files:**
- Create: `.github/workflows/build.yml`, `.github/dependabot.yml` (github-actions only)

**Interfaces:**
- Triggers: push to `main`, PRs, `workflow_dispatch`, `workflow_call` (Task 6).
- Jobs: per arch on native runners (`ubuntu-24.04`, `ubuntu-24.04-arm`): build, `check.sh`, `smoke.sh`, Trivy JSON of the candidate; one `compare` job: Trivy of the candidate (amd64) vs `docker.io/stashapp/stash:v0.31.1@sha256:df744af5…` with the same DB (`--skip-db-update` after one download) → table in the job summary; fails if any severity is higher or the total isn't lower; `publish` (main only): push by digest, multi-arch manifest `ghcr.io/neilcar/stash`, tags `<STASH_VERSION>` and `<STASH_VERSION>-<short git sha of stash-image>`, `cosign sign --recursive`, SBOM attestation; outputs `digest` and `tag`.
- Actions pinned by commit SHA.

- [ ] **Step 1: Push `initial`** and open the PR into `main` (body ends with the Claude Code line). Expected: build, check, smoke green on both arches; compare table posted and passing.
- [ ] **Step 2: Record** the compare table in the ledger. If it fails the Trivy rule, stop and report.
- [ ] **Step 3: Merge with the owner's OK**; confirm `ghcr.io/neilcar/stash:v0.31.1` is published, signed, both arches; record the digest. Make the package public if the owner agrees (GHCR packages start private; the cluster pulls without a secret for other public images).
- [ ] **Step 4: Commit** (with Step 1) — `CI: build, compare and publish`.

### Task 6: Release watcher and Fleet PR

**Files:**
- Create: `.github/workflows/watch.yml` (daily schedule + dispatch), `scripts/watch.py` (stdlib only), `scripts/fleet_pr.py` (stdlib only), `tests/test_watch.py`, `tests/test_fleet_pr.py` (pytest, run in CI)
- Modify: `.github/workflows/build.yml` (call `fleet_pr.py` after `publish` on main)

**Interfaces:**
- `watch.py`: `latest_release(releases: list[dict]) -> str | None` (newest non-draft, non-prerelease `vX.Y.Z`); `plan_bump(current_version, current_commit, latest, base_digests_now, base_digests_pinned) -> dict` (what to change, or `{}`); writes `STASH_VERSION`, `STASH_COMMIT` (resolved via the tags API) and the two `FROM` digests in `Dockerfile` (`crane digest`); the workflow commits only when something changed (bot identity, `chore: Stash <ver>` / `chore: stash-base digests`) and pushes to `main`, which triggers `build.yml`.
- `fleet_pr.py`: `update_values(text: str, repository: str, tag: str, digest: str) -> str` edits only `stash.image.{repository,tag,digest}` in `arr-values.yaml` (adds the `image:` block under `stash:` if absent, keeps comments and everything else byte-identical); `migration_note(prev_tag, new_tag) -> str` (compares the number of files in `pkg/sqlite/migrations` between the two tags via the contents API: "This release migrates the database (N new migrations); Stash backs it up first." or "No database migration."); opens or updates one PR on `neilcar/lxdk8s` from branch `stash-image/bump` into `main` with `LXDK8S_PR_TOKEN`, title `Stash <tag>`, body with the version, digest, compare table link and migration note.

- [ ] **Step 1: Write the failing tests:** `test_latest_release_skips_prereleases_and_drafts`; `test_plan_bump_no_change_is_empty` (Review Focus 5); `test_plan_bump_new_release`; `test_plan_bump_base_digest_only`; `test_update_values_adds_image_block_and_keeps_rest` (on a copy of today's `arr-values.yaml`: only lines under `stash:` change, the rest is byte-identical); `test_update_values_replaces_existing_image`; `test_migration_note_counts_new_files`; `test_fleet_pr_updates_existing_pr` (Review Focus 5; HTTP calls faked at the `urllib` boundary).
- [ ] **Step 2: Run them to see them fail.** `python -m pytest tests -q` → FAIL.
- [ ] **Step 3: Implement** both scripts and the workflow wiring.
- [ ] **Step 4: Verify.** Tests pass; `gh workflow run watch.yml` on `main` (after Task 5's merge) with no new release → no commit, no PR (log says `nothing to do`).
- [ ] **Step 5: Commit** via a PR into `main` — `Watch for Stash releases and open Fleet PRs`; merge with the owner's OK.

## Part 3 — Cutover

### Task 7: First switch and checks

- [ ] **Step 1: Back up the database:** GraphQL `backupDatabase` mutation on the running Stash (writes a dated copy next to `stash-go.sqlite` in `/config`); confirm the file exists and record its name.
- [ ] **Step 2: Open the first Fleet PR** by dispatching the `fleet_pr` step for the published `v0.31.1` image (or let Task 6's flow do it); review its diff (only `stash.image`); merge with the owner's OK; wait for the `homelab-apps` GitRepo to reach the CI-promoted `deploy` commit and the `homelab-apps-fleet-arr` bundle to be Ready.
- [ ] **Step 3: Verify on the real pod:** the pod runs `ghcr.io/neilcar/stash@<digest>`; `/healthz` 200; the library's scene count equals the pre-switch count (GraphQL `findScenes` count, recorded in Step 1); `jobQueue` empty or progressing; a live-transcode request for one HEVC/non-browser scene from the library returns a decodable stream (`ffprobe` from the runner image); the stash-scheduler plugin's next scheduled run appears in the logs; one real scrape succeeds. Ask the owner to play a file that needs transcoding in their browser and confirm.
- [ ] **Step 4: Trivy in cluster:** the trivy-operator VulnerabilityReport for the new image is below v0.31.1's per the Trivy rule; record both.
- [ ] **Step 5: Rollback (only if a check fails):** revert the Fleet PR (restoring the chart default image), wait for Fleet, confirm the old image runs; restore the Step 1 backup only if the database was changed by the new image.
- [ ] **Step 6: Record** the results in `stash-image` `README.md` (Results section) and `distroless` `README.md` (Results row) via PRs.
