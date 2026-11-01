# PhotoPrism App Pod on Distroless Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the PhotoPrism server pod on a shell-free image made of the official Plus binary copied onto `distroless/photoprism-base`, with every in-pod shell user ported first.

**Architecture:** The fork workflow (`neilcar/photoprism-k8s`, branch `k8s-261007-skip-fixes`) gains a second image, `ghcr.io/neilcar/photoprism`, built from `photoprism-base` plus `/opt/photoprism/{bin/photoprism,lib,assets}` copied from the digest-pinned official image and the `parallel-index` binary. `parallel-index` gets `pod …` subcommands that replace the bash the driver, ppsummary and friends run inside the app pod today. The switch is one lxdk8s commit, proven on the live pod.

**Tech Stack:** Go (parallel-index), bash, Docker/buildx, GitHub Actions on ARC runners `pp-amd64`/`pp-arm64`, Trivy 0.76.1, cosign 2.4.3 (legacy referrers), Helm (photoprism-plus chart), Fleet, Kyverno CLI, Python 3 stdlib (apple-photos-export).

**Spec:** `docs/superpowers/specs/2026-11-01-photoprism-app-distroless-design.md` (this repo).

## Global Constraints

- Copy, don't build: only `/opt/photoprism/bin/photoprism`, `/opt/photoprism/lib`, `/opt/photoprism/assets` come from `docker.io/photoprism/photoprism:261007@sha256:0f85369636ad99ca9a1c33f2d04df6c590802d16b7c33b4a1ea026b595be06d1`; `photoprism-debug`, `/init`, `/scripts`, Ubuntu files never.
- The app runs as uid 0 / gid 0, `ENTRYPOINT ["/opt/photoprism/bin/photoprism"]`, `CMD ["start"]`, same `ENV` block as the `photoprism-index` production stage.
- The app image's release must equal the fork's release (`261007`, from the branch/tag name); no upstream watcher.
- Package `ghcr.io/neilcar/photoprism` is private; `assert-private` runs on every pushed digest before tests and again before publish.
- Trivy: findings under `/opt/photoprism`, `/opt/darktable`, `/opt/rawtherapee`, `/opt/yt-dlp`, `/opt/parallel-index` are vendored; non-vendored C/H/M/L must be ≤ the official image's in every severity (0 where it has 0).
- Sign with `cosign sign --yes --recursive --registry-referrers-mode=legacy`, cosign v2.4.3; Kyverno verify-images Enforce.
- Every ported shell user works against both the official and the new image.
- Kyverno changes are tested with the CLI against every policy and PolicyException.
- Deploy only through lxdk8s main (Fleet). Don't restart n8n. Merges OK once checks pass.
- Switch outside 00:15–06:00 ET and not while a `photoprism-maintenance-*` or `photoprism-index-*` Job runs.
- Shared checkouts: commit only your own hunks (`photoprism-maintenance` has another session's `vision.yml` change and an unpushed commit).

## Review Focus

1. `parallel-index pod idle` run where `/proc` holds a `photoprism index` started by `kubectl exec` (not PID 1) must report it busy — Task 1 test `TestIdleReportsExecedIndex`.
2. The driver's fallback: against a pod without the binary (official image), `check_idle` must still run the bash check, not warn-and-continue — Task 1 test in `test.sh` `check_idle_falls_back`.
3. A held flock on `/photoprism/storage/faces-job/lock` counts as busy; the same file present but unheld does not — Task 1 `TestIdleLock{Held,Free}`.
4. `photoprism start` on a read-only root with only `/tmp` writable must reach `/api/v1/status` — Task 2 check `ro-root`.
5. kim's role survives: `photoprism users ls` on the new image against the live database lists `kim` as `User` — Task 6 check 3.

---

### Task 1: `parallel-index pod` subcommands and the driver/ppsummary ports

**Files:**
- Create: `setup/kubernetes/parallel-index/internal/pod/pod.go`, `pod_test.go` (repo `~/code/home/photoprism-k8s`, branch `k8s-parallel-index`)
- Modify: `setup/kubernetes/parallel-index/cmd/parallel-index/main.go` (dispatch `pod`), `main_test.go`
- Modify: `setup/kubernetes/parallel-index/parallel-index.sh:449-485` (`db_connections_left`, `check_idle`), `test.sh`
- Modify: `~/code/home/photoprism-maintenance/ppsummary.sh:39-75`; then `deploy.sh` to update the driver config map

**Interfaces:**
- Produces: `parallel-index pod idle [--locks PATH...]` → exit 0, prints one `process: <cmdline>` / `lock held: <path>` line per finding (empty = idle). `parallel-index pod db-connections-left` → prints an integer or exits 1 (reads `PHOTOPRISM_DATABASE_{SERVER,USER,PASSWORD}`, execs `mariadb … -N -e <same query>` with `MYSQL_PWD`). `parallel-index pod count-files` → stdin folder per line, stdout `<n>\t<folder>`, pruning names starting `.`, `@`, `#`, `__`, under `/photoprism/originals` (root overridable by `ORIGINALS_PATH` for tests). `parallel-index pod claims <claim_dir>` → stdin plan rows `a\tb\tc\td`, stdout `a b <done|busy|open> c` using `sha1(d)` like today.
- Go: `pod.Idle(procRoot string, locks []string) ([]string, error)`, `pod.CountFiles(root string, folders []string) map[string]int`, `pod.ClaimState(claimDir, folder string) string`.

- [ ] **Step 1: Write failing Go tests** in `pod_test.go`: `TestIdleFindsIndex` (fake proc root with `cmdline` `photoprism\x00index\x00` → one `process:` line), `TestIdleReportsExecedIndex` (same under a non-1 PID), `TestIdleIgnoresOtherCommands` (`photoprism start` → none), `TestIdleLockHeld` (a goroutine-held flock → `lock held:`), `TestIdleLockFree` (file exists, not held → none), `TestCountFilesPrunes` (`.x`, `@eaDir`, `#recycle`, `__MACOSX` skipped), `TestClaimState` (done/busy/open). In `main_test.go`: `TestRunPodUsage` (`pod` alone → exit 2).
- [ ] **Step 2: Run** `cd setup/kubernetes/parallel-index && go test ./internal/pod/ ./cmd/...` — Expected: FAIL, package `pod` undefined.
- [ ] **Step 3: Implement** `internal/pod` and the `pod` dispatch (`pod idle|db-connections-left|count-files|claims`), extending the usage line.
- [ ] **Step 4: Run** `go test ./...` — Expected: PASS.
- [ ] **Step 5: Shell fallback test first.** In `test.sh` add `check_idle_uses_binary` (stub `k` that answers `exec … /opt/parallel-index/bin/parallel-index pod idle` with `process: photoprism index` → driver dies "busy") and `check_idle_falls_back` (stub returns `executable file not found` for the binary, then the bash path's output → same verdict). Run `./ci.sh` with the freshly built binary per its header — Expected: the two new cases FAIL.
- [ ] **Step 6: Implement** in `parallel-index.sh`: `check_idle` and `db_connections_left` first try `k exec "$MAIN_POD" -- /opt/parallel-index/bin/parallel-index pod …`; only when that fails with `executable file not found`/`no such file`, run today's bash/sh body. Re-run `./ci.sh` — Expected: PASS.
- [ ] **Step 7: ppsummary.** Replace the two `bash -c` blocks: counting pipes the folder list into `kubectl exec -i "$APP_POD" -- /opt/parallel-index/bin/parallel-index pod count-files`; claim states pipe the plan rows into `… pod claims "$claim_dir"`; the `C`-row join and the awk summary run locally. Same fallback rule. Check: `bash -n ppsummary.sh && shellcheck ppsummary.sh` — Expected: clean; and against the live (official) pod with no run active it prints the Jobs line without errors.
- [ ] **Step 8: Commit and push** `k8s-parallel-index` (photoprism-k8s) — PR, CI green, merge. In photoprism-maintenance commit only `ppsummary.sh`, push; run `deploy.sh` to update the driver config map. Verify: `kubectl -n photoprism get cm photoprism-index-driver -o jsonpath='{.data.parallel-index\.sh}' | grep -c 'pod idle'` ≥ 1.

### Task 2: The `ghcr.io/neilcar/photoprism` image

**Files** (fresh worktree of `private/k8s-261007-skip-fixes`, not the stale local `wolfi-image` branch):
- Create: `docker/photoprism/wolfi/app/Dockerfile`, `docker/photoprism/wolfi/app/OFFICIAL_IMAGE`, `docker/photoprism/wolfi/app/check.sh`, `docker/photoprism/wolfi/app/release.sh`, `scripts/assert-private.sh` (copy of `pyapps-image/scripts/assert-private.sh`)
- Create: `.github/workflows/image-app.yml`
- Modify: `docker/photoprism/wolfi/PARALLEL_INDEX_REF` → Task 1's merge commit

**Interfaces:**
- Consumes: `parallel-index pod …` (Task 1), via the existing `parallel-index` build stage and named context.
- Produces: `ghcr.io/neilcar/photoprism@sha256:<index>` tagged `sha-<short>` and `k8s-261007-skip-fixes`, signed by `image-app.yml`; `DIGEST:` line in the Publish summary.

- [ ] **Step 1: Write `app/check.sh <image>`** (style of `wolfi/check.sh`): no shell at the five paths; `photoprism --version` matches `^photoprism version 261007-[0-9a-f]{7,}-Linux-(AMD64|ARM64)-Plus$`; the image's `/opt/photoprism/bin/photoprism` sha256 equals the official image's (extract both with `docker create` + `docker cp`); `photoprism-debug`, `/init`, `/scripts` absent; ffmpeg, exiftool, magick, rsvg-convert, mariadb, darktable-cli, rawtherapee-cli, heif-convert, yt-dlp resolve; `parallel-index pod` prints its usage; `start`: run detached with SQLite, `--read-only --tmpfs /tmp` and tmpfs storage/originals, poll `http://127.0.0.1:2342/api/v1/status` for 120 s → 200 (`ro-root`).
- [ ] **Step 2: Run** it against the official image: `docker pull docker.io/photoprism/photoprism:261007 && docker/photoprism/wolfi/app/check.sh docker.io/photoprism/photoprism:261007` — Expected: FAIL on the shell lines and `/init`/`/scripts` present (the version and start checks pass).
- [ ] **Step 3: Write `app/release.sh`**: prints OK when the tag in `OFFICIAL_IMAGE` equals the release in `$GITHUB_REF_NAME` (`k8s-<rel>-…` or `index-<rel>-…`), else fails. Test first: `GITHUB_REF_NAME=k8s-261008-skip-fixes app/release.sh` with `OFFICIAL_IMAGE` = `…:261007@…` — Expected: FAIL; with `k8s-261007-skip-fixes` — Expected: OK.
- [ ] **Step 4: Write `app/Dockerfile`**: build stage `parallel-index-build` as in `wolfi/Dockerfile`; `FROM ${OFFICIAL_IMAGE} AS official` (build arg from the file); production `FROM photoprism-base:latest@sha256:<current runtime digest>`, `COPY --from=official` the three paths, `COPY --from=parallel-index-build /out/parallel-index /opt/parallel-index/bin/`, the `ENV`/labels of the index stage with title `photoprism`, `ENTRYPOINT`/`CMD` per Global Constraints.
- [ ] **Step 5: Build and check locally** on a Linux host or Kane: `docker buildx build --platform linux/amd64 --build-context parallel-index=… -f docker/photoprism/wolfi/app/Dockerfile -t pp-app:test --load . && docker/photoprism/wolfi/app/check.sh pp-app:test` — Expected: all `ok`. Then `docker/photoprism/wolfi/formats.sh pp-app:test` — Expected: PASS (if it hardcodes the index entrypoint, pass the binary path, don't fork the script).
- [ ] **Step 6: Write `image-app.yml`** from `image-wolfi.yml`: same triggers, runners, Trivy pins, `meta`; adds `release.sh` in meta; build matrix pushes by digest to `IMAGE: ghcr.io/neilcar/photoprism`, then `assert-private.sh neilcar/photoprism "$DIGEST"`, then `app/check.sh`, `formats.sh`; Trivy compare with `OLD_IMAGE` = the official digest and the vendored list from Global Constraints, verdict "no worse in every severity" (`$a > $b`, or `$b == 0 and $a > 0`, fails); Publish as in `image-wolfi.yml` plus `assert-private.sh` on the manifest digest before signing, and a `DIGEST:` summary line.
- [ ] **Step 7: Push** the branch to a PR — Expected: build + check + Trivy green on both arches, Publish skipped. Merge; Expected: Publish green, `cosign verify` (Kyverno subject below) OK, anonymous pull denied.

### Task 3: Kyverno entries and the chart pull secret

**Files:**
- Modify: `~/code/home/lxdk8s/fleet/kyverno-policies/verify-images.yaml` (entry for `ghcr.io/neilcar/photoprism:*` and `@*`, subject `^https://github\.com/neilcar/photoprism-k8s/\.github/workflows/image-app\.yml@refs/(heads/k8s-261007-skip-fixes|tags/index-261007-[^/]+)$`, trigger push, `imageRegistryCredentials: {secrets: [ghcr-pull]}`), `image-sources.yaml` (allow the two references)
- Create: `~/code/home/photoprism-plus-chart/patches/0003-image-pull-secrets.patch`, `tests/pullsecrets.yaml`; Modify `tests/render.sh`
- Modify: `~/code/home/lxdk8s/fleet/photoprism/fleet.yaml` (chart version only)

- [ ] **Step 1: Kyverno test first:** `kyverno apply` all policies + exceptions on a Pod in ns photoprism using the Task 2 digest — Expected: denied by verify-images (no entry yet). Add the entries; re-run — Expected: pass; the official-image pod spec still passes; an unsigned `ghcr.io/neilcar/photoprism@sha256:<random>` is denied.
- [ ] **Step 2: Chart test first:** `tests/pullsecrets.yaml` sets `imagePullSecrets: [{name: ghcr-pull}]`; add `check pullsecrets "imagePullSecrets in the StatefulSet"` to `render.sh`; run `scripts/build.sh` + `tests/render.sh` — Expected: FAIL on the new case, `default` still PASS.
- [ ] **Step 3: Patch** the StatefulSet template (`{{- with .Values.imagePullSecrets }}`), default `[]`; bump chart version to 1.1.8; re-run — Expected: all PASS (default render unchanged).
- [ ] **Step 4: Publish** the chart (repo's CI on merge). Bump `fleet.yaml` to `1.1.8` with no value changes in its own lxdk8s PR together with the Kyverno PR; Expected after Fleet: StatefulSet generation unchanged (`kubectl -n photoprism get sts photoprism-photoprism -o jsonpath='{.metadata.generation}'` before = after).

### Task 4: apple-photos-export without a shell in the pod

**Files:** Modify `~/code/home/apple-photos-export/sync-favorites.py:250-258`, `read-capture-times.sh:75-77`; Create `tests/test_fetch_rendered.py`

- [ ] **Step 1: Test first:** `test_fetch_rendered_downloads_by_hash` runs `fetch_rendered` against a local `http.server` stub that serves `/api/v1/files/<hash>`-style lookups and `/api/v1/dl/<hash>?t=<token>` (the endpoints PhotoPrism uses; confirm from the fork's `internal/api` routes first) and asserts the bytes land in `dest`; `test_fetch_rendered_empty_raises`. Run `python3 -m unittest tests/test_fetch_rendered.py` — Expected: FAIL (it still calls kubectl).
- [ ] **Step 2: Implement** `fetch_rendered(name, dest)` via the existing `PP` client: find the sidecar file by name, download it by hash with the download token from `/api/v1/config`. Re-run — Expected: PASS.
- [ ] **Step 3: read-capture-times.sh:** prefix each batch line with `/photoprism/originals/` and run `kubectl … exec -i photoprism-photoprism-0 -- exiftool -fast2 -q -q -T -Directory -FileName -DateTimeOriginal -CreateDate -ImageWidth -ImageHeight -@ -`. Check: `shellcheck read-capture-times.sh` clean, and a 5-line batch against the live pod prints the same rows as the old command did for those files.
- [ ] **Step 4: Commit and push** (main).

### Task 5: Pre-switch record

- [ ] **Step 1:** Record, to the ledger: `photoprism --version`; `/api/v1/config` → `edition`, `membership`, `tier`, `sponsor` (via the admin app password through the API; never print secrets); `photoprism users ls` (usernames + roles only); STS generation.
- [ ] **Step 2:** Confirm no maintenance/index Job runs and the time is outside 00:15–06:00 ET.

### Task 6: The switch, proven on the live pod

**Files:** Modify `~/code/home/lxdk8s/fleet/photoprism/photoprism-values.yaml`, `fleet/kyverno-policies/image-sources.yaml` (add `photoprism` to the namespace-photoprism app-name list in `neilcar-workloads-use-neilcar-images` — in this commit, never earlier)

- [ ] **Step 1: Kyverno test first** with the rendered StatefulSet pod for the new values: passes; the same pod with `docker.io/photoprism/photoprism:261007` is denied by the new rule (proves the guard). Also the photoprism-index Job pods still pass.
- [ ] **Step 2: Values:** `image.repository: ghcr.io/neilcar/photoprism`, `image.tag: "k8s-261007-skip-fixes@sha256:<Task 2 index digest>"`, `imagePullSecrets: [{name: ghcr-pull}]`, `securityContext.readOnlyRootFilesystem: true`, a `/tmp` emptyDir in `extraVolumes`/`extraVolumeMounts`; nothing else. Render with the chart and diff against the live STS: only image, pull secret, readOnly and /tmp change.
- [ ] **Step 3: Push** to lxdk8s main; wait for the pod Ready.
- [ ] **Step 4: Checks** (spec): 1. `photoprism --version` ends `-Plus`; 2. `/api/v1/config` edition/membership/tier/sponsor equal Task 5's; 3. `photoprism users ls` lists `kim` as `User`; plus `/api/v1/status` 200, no `level=error` beyond the pre-switch pattern in 10 min of logs, `parallel-index pod idle` and `pod db-connections-left` answer via `kubectl exec`. Any failure → `git revert` the commit, push, confirm the official image back, stop.
- [ ] **Step 5: Hand to the owner:** they log in (and kim if available) and check maps and places. Owner confirms → done; else revert as in Step 4.
- [ ] **Step 6:** If PhotoPrism fails only under read-only root, ledger a ruling, drop `readOnlyRootFilesystem` in a follow-up commit, re-run Step 4.

### Task 7: Next nightly and wrap-up

- [ ] **Step 1:** After the next maintenance run: its driver log has no `could not check … for running operations` warning; ppsummary runs against the new pod.
- [ ] **Step 2:** Docs: README row in distroless for `photoprism` (consumer of photoprism-base); fork README note on `image-app.yml` and "move the app with the fork"; memory note `photoprism-app-distroless.md` + MEMORY.md line; update `photoprism-plus-chart-no-scheduling-fields.md` (fields were wired in 1.1.x).
- [ ] **Step 3:** Final whole-branch review per executing-plans; rulings and deferred minors to the owner.
