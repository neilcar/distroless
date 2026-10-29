# Servarr Apps on Distroless Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Prowlarr, Radarr, Sonarr, Whisparr and Lidarr on our own shell-free images (shared `servarr-base` in neilcar/distroless, app images from a new private `neilcar/servarr-image`), switched over one app at a time with a minutes-long rollback.

**Architecture:** `servarr-base` is an apko/Wolfi runtime with the shared libraries the self-contained .NET Servarr builds load (plus `fpcalc`). `servarr-image` downloads each app's official linux tarball (amd64/arm64) at a pinned version and SHA-256, copies it onto the base, proves every bundled native library resolves, starts each app in CI against a fixture config, compares Trivy findings with the vendor image, and publishes signed private images. The rollout overrides one app's image at a time in lxdk8s `fleet/arr/arr-values.yaml`; once clean for a day the image moves into arr-helm's `images.yaml` and auto-follow starts.

**Tech Stack:** apko/Wolfi, the `dl` CLI (distroless repo, Python, uv, pytest), bash smoke tests, GitHub Actions (native amd64/arm64 runners), cosign 2.4.3, Trivy, Helm (arr-helm), Fleet (lxdk8s).

**Spec:** `docs/superpowers/specs/2026-10-29-servarr-distroless-design.md` (neilcar/distroless)

## Global Constraints

- Shared base: apko/Wolfi, released packages only, no shell, Trivy-gated (strict: no Critical/High with a released fix), cosign-signed with **cosign 2.4.3, `--registry-referrers-mode=legacy` on `sign`** (no flag on `attest`).
- **No `sign-image.yml`** in servarr-image: `build.yml` signs every published digest itself (cosign 2.4.3, as above) and runs `cosign verify` right after. The manual re-signing workflow was retired from every other neilcar image repo on 2026-10-29, and the cluster's `verify-neilcar-images` policy only accepts the normal build workflow's signer, so add the servarr-image entry in lxdk8s for `build.yml` only.
- App images: `ghcr.io/neilcar/{prowlarr,radarr,sonarr,whisparr,lidarr}`, **private** packages, tagged with the app version (plus `<version>-<sha7>`), amd64 + arm64 on native runners, signed as above.
- Each app follows today's branch and starts at today's running version: Prowlarr `master` 2.7.0.5723, Radarr `master` 6.4.4.10685, Sonarr `main` 4.0.20.3014, Whisparr `eros` 3.6.5.1886 (hotio `v3-3.6.5-release.1886`), Lidarr `master` 3.1.6.5079. If a vendor tag moved before its app's switch, use the version the pin step (Task 6) records.
- Runtime: uid/gid 1000, `/config` owned 1000:1000, read-only root, writable `/config`, `/run`, `/tmp` (volumes the chart already mounts). Ports: Prowlarr 9696, Radarr 7878, Sonarr 8989, Whisparr 6969, Lidarr 8686.
- App-image Trivy gate: nothing Critical/High in layers we add; the app's bundled findings no worse than the vendor image it replaces; bundled findings listed in the release notes.
- No container runtime on the owner's Mac: builds and image tests run in CI.
- Deploys through Fleet GitOps (lxdk8s); every merge with the owner's OK. One app at a time; next only after a clean day. Rollback = revert that app's lxdk8s commit.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the Claude Code line.

## Review Focus

1. A bundled native library (`libe_sqlite3.so`, `libMono.Unix.so`, Whisparr's `ffprobe`) that needs a system library the base lacks: the app starts but fails later. Test: Task 2's ELF check over every `.so`/executable in the app directory (`tests/elfcheck.py`), per arch.
2. An arm64 node (mona, rk1, rk2): the tarball for arm64 must be fetched and pass the same tests. Test: Task 3 matrix runs smoke on `ubuntu-24.04-arm`.
3. Time zones, ICU and TLS: `TZ` honoured, culture-aware formatting works, HTTPS to indexers works (needs tzdata, ICU, the CA bundle and OpenSSL). Test: Task 2 smoke runs with `TZ=Europe/London` and asserts the log's startup line shows that zone, and that the log has no `Invariant` globalization or `Couldn't find a valid ICU package` warning; TLS is proven in CI by `GET /api/<v1|v3>/update` (the app fetches its update feed over HTTPS even with `UpdateMechanism=Docker`) returning 200 with at least one entry.
4. Read-only root: an app writing outside `/config`, `/tmp`, `/run` (e.g. `~/.dotnet`, `/app`). Test: Task 2 smoke runs every container with `--read-only` and tmpfs `/tmp` `/run` only.
5. Rollback after a failed switch: the vendor image must start on the data the new image touched. Test: Task 7's runbook check — after the switch's first start, revert, and confirm the vendor pod is Ready on the same `/config` (done once, for Prowlarr, before any other app moves).

---

## File Structure

| Repo / file | Responsibility |
|---|---|
| distroless `catalog.yaml`, `src/dltools/lines.py`, `state/lines.json`, `locks/servarr-base/latest/*`, `tests/smoke/test_images.sh`, `tests/test_lines.py`, `README.md` | the `servarr-base` line |
| servarr-image `versions.env` | per app: version, branch, amd64/arm64 URL + SHA-256 |
| servarr-image `scripts/fetch.py` | download + verify one app's tarball for one arch |
| servarr-image `scripts/watch.py`, `follow.env` | release watcher; per-app on/off switch (all off at first) |
| servarr-image `Dockerfile` | `ARG APP`; tarball onto `servarr-base` |
| servarr-image `tests/elfcheck.py`, `tests/smoke.sh`, `tests/fixtures/<app>/config.xml` | image tests |
| servarr-image `tests/test_fetch.py`, `tests/test_watch.py` | script unit tests (run on the Mac with uv/pytest) |
| servarr-image `.github/workflows/build.yml`, `watch.yml`, `scripts/assert-private.sh`, `scripts/trivy-compare.py` | CI |
| arr-helm `.github/scripts/update-images.py`, `test_update_images.py`, `images.yaml`, `defaults.yaml`, `README.md` | follow the new images (per app, after its switch) |
| lxdk8s `fleet/arr/arr-values.yaml` | per-app pin / trial override / rollback |

---

### Task 1: `servarr-base` in neilcar/distroless

**Files:** Modify `catalog.yaml`, `src/dltools/lines.py`, `tests/test_lines.py`, `tests/smoke/test_images.sh`, `README.md`; generated `locks/servarr-base/latest/runtime.{apko.yaml,lock.json}`, `state/lines.json` (via the repo's `dl` sync, as for sabnzbd-base #44).

**Interfaces:** Produces `ghcr.io/neilcar/distroless/servarr-base:latest` (+ digest), runtime only, `run_as: "1000"`, user `servarr` uid/gid 1000 home `/config`; `fpcalc` at `/usr/bin/fpcalc`.

- [ ] **Step 1: Test** in `tests/test_lines.py`: `test_servarr_base_line` — `servarr_base_lines(indexes) == [Line("servarr-base", "latest", "icu", "<icu version in the fixture index>")]` and `[]` for empty indexes; `test_discover_includes_servarr_base_last`.
- [ ] **Step 2:** `uv run pytest tests/test_lines.py` — Expected: FAIL (`servarr_base_lines` undefined).
- [ ] **Step 3: Implement** `servarr_base_lines(indexes) -> list[Line]` (versioned by `icu`, newest released on both arches; rank 7 after sabnzbd-base) and the catalog entry: packages `glibc`, `libstdc++`, `libgcc`, `icu`, `openssl` (libssl/libcrypto), `zlib`, `sqlite-libs`, `ca-certificates-bundle`, `tzdata`, `chromaprint` (fpcalc; if Wolfi has no released `chromaprint`, add a melange package under `packages/` like `distroless-libvips`); paths `/tmp` 01777, `/config` 0755 1000:1000, `/run` 0755 1000:1000. Environment `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false`, `XDG_CONFIG_HOME=/config`. Exact package names are confirmed against the Wolfi index by `dl` (lock-check fails on an unknown name).
- [ ] **Step 4:** `uv run pytest` — Expected: all pass. Smoke block in `tests/smoke/test_images.sh` (runs in CI): user is 1000; `fpcalc -version` prints `fpcalc version`; no `/bin/sh`; `/config` is `1000 1000`.
- [ ] **Step 5:** Commit, PR "servarr-base: distroless base for the Servarr apps", CI green (build + Trivy gate + smoke on both arches), owner merges; record the published `latest` digest.

### Task 2: servarr-image repo — fetch, Dockerfile, image tests

**Files:** Create repo `neilcar/servarr-image` (private) with `versions.env`, `scripts/fetch.py`, `Dockerfile`, `tests/elfcheck.py` (adapt sabnzbd-image's), `tests/smoke.sh`, `tests/fixtures/{prowlarr,radarr,sonarr,whisparr,lidarr}/config.xml`, `tests/test_fetch.py`, `README.md`, `.gitignore`.

**Interfaces:**
- `versions.env`: `<APP>_VERSION`, `<APP>_BRANCH`, `<APP>_URL_AMD64`, `<APP>_SHA256_AMD64`, `<APP>_URL_ARM64`, `<APP>_SHA256_ARM64` for APP in PROWLARR RADARR SONARR WHISPARR LIDARR (URLs/hashes from each app's update service: `https://{prowlarr,radarr,lidarr,whisparr}.servarr.com/v1/update/<branch>/changes?os=linux&runtime=netcore&arch=<x64|arm64>`, Sonarr `https://services.sonarr.tv/v1/update/main/changes?...`; entries carry `url` and `hash`).
- `scripts/fetch.py APP ARCH DEST` → verified tarball extracted at `DEST`; exit 1 on hash mismatch.
- `Dockerfile`: `ARG APP`, `ARG TARGETARCH`; build stage runs fetch.py; final `FROM servarr-base@<digest>`, app at `/app/bin`, `USER 1000`, `ENTRYPOINT ["/app/bin/<Binary>", "-nobrowser", "-data=/config"]` (binary per app: Prowlarr, Radarr, Sonarr, Whisparr, Lidarr), `EXPOSE <port>`, OCI labels `org.opencontainers.image.version`.

- [ ] **Step 1: Tests (unit)** `tests/test_fetch.py`: `test_fetch_rejects_wrong_hash` (local HTTP server serving a tar, wrong SHA → exit 1, nothing extracted); `test_fetch_extracts_app_dir` (right SHA → `DEST/<App>/<Binary>` exists); `test_versions_env_complete` (all 30 keys present, SHA-256 hex, URLs https).
- [ ] **Step 2:** `uv run pytest tests/test_fetch.py` — Expected: FAIL.
- [ ] **Step 3: Implement** fetch.py, versions.env (values from the update APIs at the Global Constraints versions), Dockerfile, elfcheck.py (every ELF under `/app/bin` and `/usr/bin/fpcalc` resolves all DT_NEEDED in the image), fixtures (config.xml: `Port`, `BindAddress *`, `ApiKey` fixed test value `0123456789abcdef0123456789abcdef`, `AuthenticationMethod External`, `UpdateMechanism Docker`, `Branch` as above, `LogLevel info`), smoke.sh `APP IMAGE`.
- [ ] **Step 4:** `uv run pytest` — Expected: PASS. smoke.sh assertions (run in Task 3's CI): container `--read-only --tmpfs /tmp --tmpfs /run --user 1000:1000 -v <fixture copy>:/config`, `-e TZ=Europe/London`; `/ping` returns `{"status":"OK"}` within 120 s; `GET /api/<v1|v3>/system/status` with `X-Api-Key` returns `version == <APP>_VERSION`, `isDocker` true, `branch == <APP>_BRANCH`; the app's SQLite DB exists in `/config` after start; restart the container on the same `/config` and `/ping` is OK again (migrations idempotent); log contains no `Invariant` globalization warning and no `DllNotFoundException`; Lidarr only: `/usr/bin/fpcalc -version` inside the image.
- [ ] **Step 5:** Commit; create the private GitHub repo and push `main`.

### Task 3: servarr-image CI — build, test, Trivy compare, publish, sign

**Files:** `.github/workflows/build.yml`, `scripts/assert-private.sh`, `scripts/trivy-compare.py`, `tests/test_trivy_compare.py`, `tests/test_assert_private.py` (adapt sabnzbd-image's).

**Interfaces:** matrix `app × arch` (`ubuntu-24.04`, `ubuntu-24.04-arm`); job outputs per app the manifest digest; publishes only on `main` and `v*` tags; `trivy-compare.py NEW.json OLD.json` exits 1 when the new image has more unique (ID, package) Critical+High pairs than the old one, or any Critical/High in OS packages (Wolfi layer); prints a Markdown table for the release notes. Vendor images to compare against: today's linuxserver/hotio images by digest (from the cluster's running pods, written into the workflow env).

- [ ] **Step 1: Tests** `tests/test_trivy_compare.py`: `test_fails_on_os_package_high`, `test_fails_when_bundled_findings_grow`, `test_passes_when_bundled_findings_shrink_or_equal`, `test_table_lists_bundled_findings`.
- [ ] **Step 2:** `uv run pytest tests/test_trivy_compare.py` — Expected: FAIL.
- [ ] **Step 3: Implement** trivy-compare.py and the workflows: build per arch (push by digest), elfcheck + smoke on that digest, Trivy (`--format json`) new vs vendor, merge the two arch digests into the tagged manifest list only when both pass, `cosign-installer` with `cosign-release: v2.4.3`, `cosign sign --yes --recursive --registry-referrers-mode=legacy`, SBOM attest per arch, `assert-private.sh` after publish, GitHub release per app version with the Trivy table.
- [ ] **Step 4:** `uv run pytest` PASS; push a branch, run the workflow (`workflow_dispatch`) — Expected: all ten build/test jobs green, Publish skipped on the branch; Trivy table shows each app's counts vs vendor.
- [ ] **Step 5:** PR, owner merges; the `main` run publishes five images. Owner grants `neilcar/arr-helm` **Read** on each of the five packages (GitHub UI → package → Manage Actions access; no API — same as SABnzbd). Kyverno admission dry-run (`kubectl create --dry-run=server -n apps` with `ghcr-pull`) admits each published digest.

### Task 4: servarr-image release watcher (off for every app)

**Files:** `scripts/watch.py`, `follow.env` (`FOLLOW_PROWLARR=0` … `FOLLOW_LIDARR=0`), `.github/workflows/watch.yml` (daily), `tests/test_watch.py`.

**Interfaces:** `watch.py` reads `follow.env`; for each app with `FOLLOW_<APP>=1`, queries its update API for its branch, and when a newer version exists rewrites that app's six `versions.env` lines and opens a PR "<app> <version>". Apps with `0` are never touched.

- [ ] **Step 1: Tests:** `test_skips_apps_not_followed`, `test_updates_only_followed_app_lines`, `test_rejects_hash_missing`, `test_picks_newest_on_branch`.
- [ ] **Steps 2–4:** fail, implement, pass (`uv run pytest`).
- [ ] **Step 5:** Commit, PR, owner merges.

### Task 5: arr-helm can follow the new images (inactive until each app moves)

**Files:** `.github/scripts/update-images.py`, `.github/scripts/test_update_images.py`.

**Interfaces:** `REGISTRY_TAGS["ghcr.io/neilcar/<app>"] = re.compile(r"^\d+\.\d+\.\d+\.\d+$")` and the five in `REBUILDS_AT_ONCE`. No `images.yaml` change here: an app's entry only points at `ghcr.io/neilcar/<app>` in Task 8.

- [ ] **Step 1: Test** `test_servarr_images_follow_four_part_versions` (tag `2.7.0.5723` → newer `2.7.1.5800` picked; `latest` ignored).
- [ ] **Steps 2–4:** fail, implement, pass (`python -m pytest .github/scripts`).
- [ ] **Step 5:** Commit, PR, owner merges (no chart version bump needed: the script isn't in the chart).

### Task 6: Pin today's vendor images (no-op rollout)

**Files:** lxdk8s `fleet/arr/arr-values.yaml`.

- [ ] **Step 1:** For each of the five apps, set `<app>.image.repository/tag/digest` to exactly what runs now (read from the live Deployments), with a comment block explaining the servarr rollout. Record the versions; if any differs from the Global Constraints table, update `versions.env` in servarr-image (PR) before that app's switch.
- [ ] **Step 2:** `helm template` the arr chart with the new values: the five Deployments' images are identical to the live ones (`diff` of image lines empty).
- [ ] **Step 3:** PR, owner merges; Fleet rolls out with no pod restarts (`kubectl -n apps get pods` ages unchanged).

### Task 7: Switch Prowlarr (and prove the rollback)

**Files:** lxdk8s `fleet/arr/arr-values.yaml`.

- [ ] **Step 1:** Back up `/config/prowlarr.db`, `logs.db`, `config.xml` to `/config/backup-pre-distroless-YYYYMMDD/` inside the pod (busybox-free: via `kubectl exec ... -- cp` on the vendor image, which has a shell).
- [ ] **Step 2:** Commit the override to `ghcr.io/neilcar/prowlarr:<version>@<digest>`; PR; owner merges; Fleet rolls out.
- [ ] **Step 3: Checks:** pod Ready; `/ping` OK; `system/status` version equal; every indexer's test passes (`POST /api/v1/indexer/testall`); the apps sync (Prowlarr → Radarr/Sonarr/Lidarr/Whisparr application sync shows no errors); no new errors in its log for 30 min.
- [ ] **Step 4: Rollback drill (once):** revert the commit; confirm the vendor pod is Ready on the same `/config` and indexers test green; re-apply the switch. Expected: both directions within minutes.
- [ ] **Step 5:** Clean day: no new errors, RSS syncs running. Then Task 8 for Prowlarr.

### Task 8: Make a switched app permanent (per app, after its clean day)

**Files:** arr-helm `images.yaml`, `defaults.yaml` (Whisparr: security context), `README.md`, `Chart.yaml` (version bump); lxdk8s `fleet/arr/arr-values.yaml`; servarr-image `follow.env`.

- [ ] **Step 1:** arr-helm PR: `<app>` entry in `images.yaml` → `ghcr.io/neilcar/<app>`, same tag and digest as the override; chart patch bump; owner merges; the release opens the lxdk8s "arr chart X" PR — before merging it, in the same lxdk8s change remove that app's override (so the rendered image is unchanged: `helm template` diff empty for that app).
- [ ] **Step 2:** servarr-image PR: `FOLLOW_<APP>=1`; owner merges.
- [ ] **Step 3:** Verify: the app's pod did not restart (image unchanged); `update-images.py --dry-run` lists the app's tag as followed.

### Tasks 9–12: Switch Radarr, Sonarr, Whisparr, Lidarr (one at a time, each then Task 8)

Same steps as Task 7 (no rollback drill), with per-app checks:
- **Radarr / Sonarr:** download clients test green; a manual search returns results; an import from `/complete` succeeds (watch the next completed download).
- **Whisparr:** the override commit also sets `whisparr.securityContext` / `podSecurityContext` to the other apps' values (uid/gid 1000, read-only root, `fsGroup` 1000, `/run` and `/tmp` writable volumes as the chart gives the others); reverting the commit restores both. Checks as Radarr; ffprobe runs on an import.
- **Lidarr:** back up `lidarr.db`/`logs.db`/`config.xml` only (21 GB of covers stays); checks as Radarr plus fpcalc used on an import (no "fpcalc not found" in the log); album search returns results.

Each: owner merges every PR; next app only after a clean day.

### Task 13: Wrap-up

- [ ] README in servarr-image and arr-helm (what each image is, how to roll back, how auto-follow is switched on); distroless README Results row for `servarr-base`; memory note.
- [ ] Remove the dated `/config/backup-pre-distroless-*` folders after the last app's clean week (owner's OK).
