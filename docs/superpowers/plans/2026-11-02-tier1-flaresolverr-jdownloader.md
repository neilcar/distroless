# Tier 1 FlareSolverr + JDownloader on distroless — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FlareSolverr and JDownloader run on shell-free, signed, private neilcar images, with FlareSolverr proven as reliable as today before it switches, and JDownloader headless (MyJDownloader only) with its code fixed in the image and updated weekly by itself.

**Architecture:** Two new bases in `neilcar/distroless` (`flaresolverr-base`: Python + Wolfi Chromium; `jdownloader-base`: Wolfi JRE + what JDownloader loads). FlareSolverr builds in `neilcar/pyapps-image` next to Tautulli/SearXNG/beets. JDownloader gets `neilcar/jdownloader-image`, whose JDownloader code is a snapshot tarball (fetched with JDownloader's own updater, published as a release asset, pinned by SHA-256). Deploys go through lxdk8s Fleet GitOps; FlareSolverr's image comes from the arr chart (`arr-helm/images.yaml`). JDownloader stays a Helm deploy (owner's decision) but on our own chart, `oci://ghcr.io/neilcar/charts/jdownloader`, kept in `neilcar/jdownloader-image` under `chart/` (the pmoscode chart's probes need the desktop's web port). Both images build for amd64 and arm64 (owner's decision), and JDownloader loses its amd64 pin.

**Tech Stack:** apko/Wolfi (distroless `dl` tooling), Docker Buildx on ARC runners, cosign 2.4.3, Trivy 0.76.1, Kyverno CLI, Fleet, Python 3 (scripts + pytest), bash smoke tests.

**Spec:** `/Users/rando/code/home/distroless/docs/superpowers/specs/2026-11-02-tier1-flaresolverr-jdownloader-design.md`

## Global Constraints

- Images: `ghcr.io/neilcar/flaresolverr`, `ghcr.io/neilcar/jdownloader`; private GHCR (assert-private step); cosign 2.4.3 `--registry-referrers-mode=legacy`; covered by Kyverno `verify-neilcar-images` (Enforce).
- No shell, read-only root, restricted pod-security set; FlareSolverr uid 1000; JDownloader non-root uid 1000 (volume is 1000:1000; `/complete` is 0777 911:1001).
- FlareSolverr stays at v3.5.2 (no upgrade in the switch); same URL, port 8191, Prowlarr unchanged.
- JDownloader: no change to settings, download list, accounts, Event Scripter scripts, download folders (`/output`, `/complete`) or MyJDownloader device name. Self-update off from the image side only; never edit `UpdateSettings` in the live `/config/cfg` (fallback only if impossible, then the revert runbook re-enables updates). Old code copies on the volume stay in place.
- JDownloader: Helm deploy on our chart; images for amd64 and arm64; no nodeSelector (every worker mounts `/mnt/downloads`, `infra/fstab-downloads.md`; the PVC is Longhorn RWO, so it follows the pod).
- JDownloader updates: weekly batched PR, merges itself after the image's smoke tests pass, rolls out through Fleet with no owner OK; manual "rebuild now" dispatch takes the same path.
- FlareSolverr gate: the new image solves every challenge the old one solves (≥20 ExtraTorrent + ≥20 PornRips requests over a few hours, side by side on mona), in comparable time. If not: stop FlareSolverr, report to the owner with results and options; JDownloader carries on.
- Trivy: nothing Critical/High in what we add; app images no worse than the vendor image they replace (`flaresolverr/flaresolverr:v3.5.2@sha256:c80ae007ce2ccdcd217a12426e4f039ef763ff90738c808d38810c3e59323767`, `jlesage/jdownloader-2:v26.09.1`).
- Every manifest change: Kyverno CLI against every policy and PolicyException, on the rendered chart/bundle. kubectl context `default`. Merges after checks pass (owner's standing OK for this series); new Fleet bundle paths go into the live GitRepo and `fleet/README.md` without asking.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the Claude Code line.

## Review Focus

1. **Revert to jlesage after the new image ran on the volume:** jlesage must start on that `cfg` with the download list and MyJD login intact — pinned by Task 7's `revert-readback` smoke case.
2. **JDownloader writing the update override back into `cfg`:** `UpdateSettings.json` must be byte-identical after a run — Task 7's `no-cfg-writeback` smoke case.
3. **Chromium under pod constraints** (read-only root, tmpfs `/tmp`, default 64 MiB `/dev/shm`, uid 1000, no capabilities): must solve, not crash — Task 2's smoke runs with exactly those flags.
4. **The auto-merge path merging something other than a JDownloader bump:** the merge step must refuse a PR that touches any file outside its allowlist — Task 8's `test_refuses_foreign_files`.
5. **Event Scripter's webhook after the switch:** the scripts JSON must load and the extension be enabled in the headless start — Task 7's `eventscripter-loaded` smoke case.

---

### Task 1: `flaresolverr-base` in neilcar/distroless

**Files:**
- Modify: `distroless/catalog.yaml` (new `flaresolverr-base` image after `beets-base`)
- Create: `distroless/locks/flaresolverr-base/latest/*` (via `dl` tooling)
- Modify: distroless smoke test for the image (where `beets-base`'s lives), `README.md` image table

**Interfaces:**
- Produces: `ghcr.io/neilcar/distroless/flaresolverr-base:latest@sha256:…` (runtime) and `:latest-dev` (dev), uid/gid 1000 `flaresolverr`, home `/config`; `/usr/bin/chromium` and `/usr/bin/chromedriver` (or the Wolfi paths, recorded in the catalog comment), `Xvfb` only if FlareSolverr needs it on Wolfi (decide by running FlareSolverr's `HEADLESS=true` mode in the dev variant first).

- [ ] **Step 1:** Add the smoke assertions first: runtime has no `/bin/sh`; `chromium --headless=new --no-sandbox --dump-dom data:text/html,<p>ok</p>` prints `<p>ok</p>` as uid 1000 with read-only root and tmpfs `/tmp`; `chromedriver --version` major equals `chromium --version` major.
- [ ] **Step 2:** Run the smoke test against the current catalog. Expected: FAIL (image not defined).
- [ ] **Step 3:** Add `flaresolverr-base` (python line matching FlareSolverr v3.5.2's `requirements.txt` Python; packages `{package}`, `distroless-no-shell`, `chromium`, chromedriver package, fonts `ttf-dejavu` + `font-noto` equivalents, Xvfb if needed). Then `dl sync`, revert unrelated lines, `apko lock`, `dl pin-released --index-dir`, `dl lock-check`.
- [ ] **Step 4:** Run the smoke test. Expected: PASS for amd64 and arm64.
- [ ] **Step 5:** Commit, PR, merge after CI; if the build skips, `gh workflow run build.yml -f filter=flaresolverr-base`. Record the published runtime and dev digests in the ledger.

### Task 2: `flaresolverr` image in neilcar/pyapps-image

**Files:**
- Create: `pyapps-image/Dockerfile.flaresolverr`, `requirements/flaresolverr.in`, `requirements/flaresolverr.txt` (hash-pinned), `tests/fixtures/flaresolverr/challenge.html` (a local page FlareSolverr fetches)
- Modify: `versions.env` (`FLARESOLVERR_VERSION=3.5.2`, `FLARESOLVERR_URL`, `FLARESOLVERR_SHA256` of the GitHub tag tarball), `follow.env` (`FOLLOW_FLARESOLVERR=0`), `scripts/fetch.py`, `scripts/inputs.py`, `scripts/watch.py` (`APPS` += `FLARESOLVERR`, GitHub releases like Tautulli, tag `vX.Y.Z`), `tests/smoke.sh` (`flaresolverr)` case), `tests/test_watch.py`, `tests/test_inputs.py`, `.github/workflows/build.yml` (matrix app + vendor), `README.md`
- Modify: `lxdk8s/fleet/kyverno-policies/verify-images.yaml` (pyapps-image entry: add `ghcr.io/neilcar/flaresolverr:*` and `@*`)

**Interfaces:**
- Consumes: Task 1's digests.
- Produces: `ghcr.io/neilcar/flaresolverr:3.5.2@sha256:…` (both arches), listening on 8191, uid 1000, `ENTRYPOINT` running `flaresolverr.py`; GitHub release `flaresolverr-v3.5.2`.

- [ ] **Step 1:** Write `test_watch.py::test_flaresolverr_follows_github_release` (fake upstream returns `v3.5.3` → prints `CHANGED flaresolverr 3.5.3`, rewrites the three lines; `v4.0.0` → not followed) and `test_inputs.py::test_flaresolverr_inputs` (Dockerfile, requirements txt, versions lines). Run `python3 -m pytest -q tests`. Expected: FAIL on the new tests only.
- [ ] **Step 2:** Implement the watcher/inputs/fetch additions. Run the suite. Expected: PASS.
- [ ] **Step 3:** Write the smoke case: run with `--read-only --tmpfs /tmp --user 1000:1000 --cap-drop ALL` (default shm); `GET /health` → `{"status":"ok"}`; `POST /v1 {"cmd":"request.get","url":"http://<host>:<port>/challenge.html","maxTimeout":60000}` → `status: ok`, `solution.status: 200`, response contains the fixture's marker text; log has no `Traceback`; the no-shell checks already in smoke.sh. Run it against the stock image to confirm the case is valid (Expected: PASS except the no-shell check), then against nothing built yet (Expected: FAIL).
- [ ] **Step 4:** Write `Dockerfile.flaresolverr` on `flaresolverr-base` (build stage on `-dev`: fetch source, pip install hash-pinned deps into a site dir; runtime: copy, `ENV` matching the stock image's defaults except paths, `USER 1000:1000`, undetected_chromedriver's working dir under `/tmp`). Add the build matrix entry with `vendor:` the stock digest. Push a branch; CI must pass build, elfcheck, smoke, Trivy on both arches.
- [ ] **Step 5:** Kyverno verify-images change in lxdk8s (own PR), tested with the Kyverno CLI against every policy and exception. Merge pyapps-image then lxdk8s after checks; record the published digest.

### Task 3: Side-by-side canary on mona

**Files:**
- Create: `lxdk8s/fleet/flaresolverr-canary/{fleet.yaml,flaresolverr-canary.yaml}` (Deployment + ClusterIP Service `flaresolverr-canary:8191`, `apps` ns, nodeSelector `kubernetes.io/hostname: mona`, the Task 2 digest, restricted securityContext, `/tmp` emptyDir, same 768Mi request and `LOG_LEVEL=info`)
- Create: `pyapps-image/tools/compare-solvers.py` + `tests/test_compare_solvers.py`
- Modify: `lxdk8s/fleet/README.md`; live GitRepo `homelab-apps` paths (+ `fleet/flaresolverr-canary`)

**Interfaces:**
- Produces: `compare-solvers.py --old URL --new URL --urls FILE --rounds N --gap SECONDS --out results.jsonl` sending each URL to both solvers in the same round (order alternated), recording per request `{round, url, solver, ok, http_status, challenge_detected, seconds}`; `--summary results.jsonl` prints per site and solver: requests, solved, failures, median seconds, and exits 1 if `new` failed any request that `old` solved in the same round.

- [ ] **Step 1:** Write `test_compare_solvers.py` with a fake solver pair: (a) both solve → exit 0; (b) old ok, new timeout in one round → exit 1 and the round is listed; (c) both fail the same round → exit 0, counted for both. Run. Expected: FAIL (module missing).
- [ ] **Step 2:** Implement; run the tests. Expected: PASS.
- [ ] **Step 3:** Add the canary bundle; Kyverno CLI on the rendered bundle against every policy and exception; PR, merge, add the GitRepo path; wait for the pod Ready on mona.
- [ ] **Step 4:** URL file: the ExtraTorrent and PornRips search URLs Prowlarr sent in FlareSolverr's log (taken from the current log, no secrets in them). Run from a pod-network vantage (a short-lived Job on the Task 2 image is not possible without a shell — run the script from Kane through `kubectl port-forward` to both Services) with `--rounds 20 --gap 600` (≈3.5 h), in the background.
- [ ] **Step 5:** `--summary`. Expected: exit 0 and new median within ~1.5× old. **If exit 1 or much slower: stop FlareSolverr here** (ledger it, leave the canary running for diagnosis, report results + options to the owner) and go to Task 5.

### Task 4: FlareSolverr switch

**Files:**
- Modify: `arr-helm/images.yaml` (`flaresolverr:` → `ghcr.io/neilcar/flaresolverr`, tag `3.5.2`, Task 2 digest; header comment), `arr-helm/Chart.yaml` version bump
- Modify: `lxdk8s/fleet/arr/fleet.yaml` (chart version), `fleet/arr/arr-values.yaml` (`flaresolverr:` restricted securityContext + `automountServiceAccountToken: false` as bandcampsync, `/tmp` emptyDir if the chart's `/config` emptyDir isn't enough), `fleet/kyverno-policies/image-sources.yaml` (`flaresolverr` into `neilcar-workloads-use-neilcar-images`); delete `fleet/flaresolverr-canary`, its GitRepo path and README row
- Package settings: give `neilcar/arr-helm` Read on the `flaresolverr` package (as for beets)

- [ ] **Step 1:** Record the baseline: Prowlarr `failed_queries` and `queries` for ExtraTorrent (id 26) and PornRips (id 29) via the arr MCP, and FlareSolverr's solved/detected counts.
- [ ] **Step 2:** arr-helm PR (its CI renders/tests); merge; chart released.
- [ ] **Step 3:** lxdk8s PR with the chart bump, values, policy and canary removal; Kyverno CLI on the rendered arr bundle against every policy and exception. Merge after fleet-render passes.
- [ ] **Step 4:** Verify: pod Ready on its usual node with the neilcar digest; a Prowlarr search on ExtraTorrent returns results; FlareSolverr log shows `Challenge solved!`.
- [ ] **Step 5:** After a day: deltas of Step 1's counters no worse than the baseline rate; otherwise revert the lxdk8s commit and report.

### Task 5: `jdownloader-base` in neilcar/distroless

**Files:**
- Modify: `distroless/catalog.yaml` (`jdownloader-base`), locks, smoke test, README table

**Interfaces:**
- Produces: `ghcr.io/neilcar/distroless/jdownloader-base:latest@sha256:…` + `-dev`; uid/gid 1000 `jdownloader`, home `/config`; a Wolfi OpenJDK JRE (newest LTS that runs JDownloader revision 50639 headless — check with the dev variant before locking), `ffmpeg`, `ffprobe`, `libstdc++`/`libgcc` (the 7-Zip-JBinding native lib JDownloader ships; it has aarch64 builds — check JD loads it on arm64). amd64 and arm64.

- [ ] **Step 1:** Smoke assertions first: no `/bin/sh`; `java -version` runs as 1000 with read-only root; `java -Djava.awt.headless=true -XshowSettings:properties -version` shows headless; `ffmpeg -version` runs. Run. Expected: FAIL (not defined).
- [ ] **Step 2:** Add the catalog entry; `dl` lock steps as Task 1.
- [ ] **Step 3:** Smoke test. Expected: PASS.
- [ ] **Step 4:** Commit, PR, merge, build (dispatch if skipped); record digests.

### Task 6: neilcar/jdownloader-image repo, snapshot and runners

**Files:**
- Create repo `neilcar/jdownloader-image` (private), with `README.md`, `versions.env` (`JD_REVISION`, `JD_BUILD_DATE`, `JD_URL`, `JD_SHA256`), `scripts/snapshot.py`, `scripts/assert-private.sh` + `scripts/trivy-compare.py` (copied from pyapps-image), `tests/test_snapshot.py`
- Create: `lxdk8s/fleet/arc-runner-jdownloader-image-{amd64,arm64}/{fleet.yaml,values.yaml}` (copies of pyapps-image's, scale sets `jdownloader-amd64` on amd1 and `jdownloader-arm64` on mona, idle 0, max 2), README row, GitRepo paths; GitHub App installation covers the repo

**Interfaces:**
- Produces: `snapshot.py fetch OUT_DIR` (runs JDownloader's updater headless inside `jdownloader-base:-dev` until `build.json` exists and the updater reports no pending update; exits non-zero after 15 min), `snapshot.py pack OUT_DIR TARBALL` (deterministic tar: sorted, mtime 0, uid/gid 0, only `JDownloader.jar Core.jar jd/ libs/ extensions/ themes/ translations/ licenses/ build.json`; never `cfg/`, `logs/`, `tmp/`), `snapshot.py revision DIR` → `JDownloaderRevision` from `build.json`; `snapshot.py set-version VERSIONS TARBALL URL` rewrites the four lines. Release asset name `jd-r<revision>.tar.gz` on release `snapshot-r<revision>`.

- [ ] **Step 1:** `test_snapshot.py`: `pack` of a fixture dir excludes `cfg/`, `logs/`, `tmp/` and is byte-identical across two runs; `revision` reads `50639` from a fixture `build.json`; `set-version` rewrites exactly the four lines. Run. Expected: FAIL.
- [ ] **Step 2:** Implement; tests PASS.
- [ ] **Step 3:** Runner bundles in lxdk8s (Kyverno CLI, PR, merge, GitRepo paths); confirm both scale sets register.
- [ ] **Step 4:** The snapshot is architecture-independent except `libs/` natives (JD ships both); fetch it once on amd64. First snapshot by hand through a `snapshot.yml` workflow (dispatch-only for now): fetch, pack, upload to release `snapshot-r<rev>`, print SHA-256. Commit `versions.env` with it.

### Task 7: jdownloader image build, smoke tests, publish

**Files:**
- Create: `jdownloader-image/Dockerfile`, `tests/smoke.sh`, `tests/fixtures/cfg/` (minimal: EventScripter enabled with a script POSTing to a local listener, a one-link download list, MyJD settings with a dummy account and device name `fixture-id`, `UpdateSettings.json` copied from the live shape), `.github/workflows/build.yml`
- Modify: `lxdk8s/fleet/kyverno-policies/verify-images.yaml` (new entry for `ghcr.io/neilcar/jdownloader`, subject `https://github.com/neilcar/jdownloader-image/.github/workflows/build.yml@refs/heads/main`)

**Interfaces:**
- Consumes: Task 5 digests, Task 6 `versions.env` + snapshot asset.
- Produces: `ghcr.io/neilcar/jdownloader:r<revision>@sha256:…` (multi-arch index, amd64 + arm64), code under `/opt/jdownloader` (read-only), entrypoint `java` with headless + update-disabling options and JD home pointing state (`cfg`, `logs`, `tmp`) at `/config`; GitHub release `jdownloader-r<revision>`.

- [ ] **Step 1:** Smoke cases (bash, each run `--read-only --tmpfs /tmp --user 1000:1000 --cap-drop ALL -v fixture:/config`):
  - `no-shell`: `/bin/sh`, busybox absent.
  - `starts-headless`: within 120 s the JD log under `/config/logs` shows the start-up complete line and no `HeadlessException`/stack trace.
  - `no-update`: no update-server request in the log (`update` client lines) for 3 minutes; no new files in `/opt/jdownloader` (read-only anyway) or `/config/update`.
  - `no-cfg-writeback`: `cfg/org.jdownloader.updatev2.UpdateSettings.json` sha256 identical before and after.
  - `eventscripter-loaded`: log shows the Event Scripter extension initialised with 1 script.
  - `downloadlist-kept`: the fixture link is still in the download list file after a restart.
  - `revert-readback`: then start `jlesage/jdownloader-2:v26.09.1` (pinned digest) on the same fixture copy with its self-update blocked by network `none`; its JD log shows the same download list size and the MyJD device name `fixture-id`.
  Run against nothing built. Expected: FAIL.
- [ ] **Step 2:** Dockerfile: build stage fetches the snapshot by `JD_URL` and checks `JD_SHA256`, unpacks into `/opt/jdownloader`; runtime on `jdownloader-base`, `USER 1000:1000`. Find the update-disabling mechanism (system properties / start flags / read-only overlay of the update config resolved from the image) that passes `no-update` and `no-cfg-writeback`; if no image-side mechanism passes, ledger a ruling and fall back per the spec (cfg edit + revert-runbook step).
- [ ] **Step 3:** `build.yml` (pyapps-image's shape, native matrix amd64 + arm64 on the two scale sets, smoke tests on both, vendor = jlesage digest per arch, sign with cosign 2.4.3 legacy, verify, SBOM, release notes). Push; CI green on the branch.
- [ ] **Step 4:** Kyverno verify-images entry (own lxdk8s PR, Kyverno CLI). Merge both; record the published digest.

### Task 8: Weekly automated updates

**Files:**
- Create: `jdownloader-image/.github/workflows/watch.yml` (weekly cron, CRON in UTC, + `workflow_dispatch` "rebuild now"), `scripts/auto-merge.py`, `scripts/open-fleet-pr.py` (from pyapps-image, rewriting the image tag/digest lines in `fleet/jdownloader/jdownloader-values.yaml`), `tests/test_auto_merge.py`, `tests/test_open_fleet_pr.py`

**Interfaces:**
- Produces: `auto-merge.py --repo OWNER/REPO --pr N --allow GLOB...` waits for all PR checks (`gh pr checks --watch`), refuses (exit 2) if any changed file is outside the allowlist or any check failed, else squash-merges. Allowlists: jdownloader-image PRs `versions.env`, `Dockerfile` (base digest lines only); lxdk8s PRs `fleet/jdownloader/jdownloader-values.yaml` only (image lines; a chart version bump in `fleet/jdownloader/fleet.yaml` too when the chart changed).
- Flow: watch.yml runs `snapshot.py fetch/pack`; if revision > `JD_REVISION` or a base digest changed → upload asset, PR, `auto-merge.py`. On main, build.yml publishes, then opens the lxdk8s PR with the neilcar-homelab App and runs `auto-merge.py` on it (fleet-render must pass).

- [ ] **Step 1:** `test_auto_merge.py::test_refuses_foreign_files`, `::test_refuses_failed_check`, `::test_merges_when_green` (fake `gh`), `test_open_fleet_pr.py::test_rewrites_only_image_line`. Run. Expected: FAIL.
- [ ] **Step 2:** Implement; tests PASS.
- [ ] **Step 3:** Workflows; dry-run dispatch (`dry_run: true` input → stops before PRs) shows "no newer revision" or the would-be PR.
- [ ] **Step 4:** Merge; first scheduled run date in the ledger.

### Task 9: JDownloader chart and switch (owner trial)

**Files:**
- Create: `jdownloader-image/chart/` (Chart.yaml `name: jdownloader`, version 0.1.0, appVersion `r<revision>`; templates: Deployment, Service, ServiceAccount off), its `helm lint` + `helm template` tests in CI, and a publish job pushing `oci://ghcr.io/neilcar/charts/jdownloader` on main when `chart/` changes (package private; give `neilcar/lxdk8s`'s fleet-render token Read).
- Chart behaviour: values `image.{repository,tag,digest}` (deploys `repository:tag@digest`), `persistence.existingClaim`, `additionalVolumes`/`additionalVolumeMounts`, `resources`, `nodeSelector`/`tolerations`/`affinity` (empty by default), `fullnameOverride`; fixed: `Recreate`, restricted securityContext uid/gid 1000 + fsGroup 1000 + RuntimeDefault seccomp + drop ALL + readOnlyRootFilesystem, `automountServiceAccountToken: false`, `/tmp` emptyDir, PVC subPaths `config`→`/config` and `downloads`→`/output`, tcpSocket probes on the MyJD direct-connect port 3129 if it listens (else none), Service port 3129 (`myjd`); no web port, no MyJD env (credentials and device name are already in `cfg`).
- Modify: `lxdk8s/fleet/jdownloader/fleet.yaml` (chart `oci://ghcr.io/neilcar/charts/jdownloader`, same `releaseName: jdownloader`, `takeOwnership: true`), `jdownloader-values.yaml` (`fullnameOverride: jdownloader-jdownloader2` to keep object names, image pins, existing claim, `/complete` hostPath, 768Mi; **no nodeSelector**); `fleet/kyverno-policies/image-sources.yaml` (the pod's name label into `neilcar-workloads-use-neilcar-images`); `fleet/jdownloader-oauth2-proxy` untouched (stays, shows nothing).

- [ ] **Step 0:** Chart tests first: `helm template` with the lxdk8s values renders exactly one Deployment named `jdownloader-jdownloader2` with no `nodeSelector`, `readOnlyRootFilesystem: true`, `runAsUser: 1000`, image `ghcr.io/neilcar/jdownloader:<tag>@<digest>`, mounts `/config`, `/output`, `/complete`, `/tmp`, and no port 5800. Expected: FAIL (no chart), then PASS after writing it. Publish the chart.
- [ ] **Step 1:** Render the bundle and run the Kyverno CLI against every policy and PolicyException (the existing hostPath exception must still match the new pod's labels). Expected: pass.
- [ ] **Step 2:** Backup: `cfg` → `/config/cfg.bak-20261102` (or the switch date) via a non-root busybox `kubectl debug --profile=baseline` container (not the toolbox image).
- [ ] **Step 3:** PR, merge after fleet-render; pod Ready (on whichever node, amd64 or arm64 — note which); JD log shows MyJD connected, no update check.
- [ ] **Step 4:** Owner checks (ask them): device online in MyJDownloader with the existing list; a new link downloads to the usual place; n8n receives the "download finished" webhook (n8n execution list, no `includeData`); an archive extracts.
- [ ] **Step 5:** Ledger the result. Revert runbook in the PR body: revert the commit (jlesage returns, self-updates itself, desktop back behind the GitHub login).

### Task 10: Wrap-up

**Files:**
- Modify: `distroless/README.md` results rows; memory (`pyapps-distroless-images.md` for FlareSolverr, new `jdownloader-distroless.md`, MEMORY.md lines)

- [ ] **Step 1:** README rows and memory notes (incl. the canary result, the update mechanism, the revert runbook).
- [ ] **Step 2:** When the owner keeps the new JDownloader: follow-up lxdk8s PR removing `fleet/jdownloader-oauth2-proxy`, its tailnet ingress, its Infisical secret mapping and GitRepo path. Not before.
