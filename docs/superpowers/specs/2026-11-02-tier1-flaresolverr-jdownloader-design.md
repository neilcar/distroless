# Tier 1 images on distroless (FlareSolverr, JDownloader) — design

Status: reviewed (builder check), 2026-11-02.

## Why

Tier 1 is the set of high-exposure third-party images: transmission (skipped
by the owner), the PhotoPrism app pod (done 2026-11-01), FlareSolverr and
JDownloader. The last two still run vendor images that ship a shell, a package
manager and, for JDownloader, a whole desktop (X server, window manager,
noVNC) that the owner rarely uses, plus a JDownloader that rewrites its own
code on the data volume.

## Goals

- **FlareSolverr** runs on `ghcr.io/neilcar/flaresolverr`: the same
  FlareSolverr release as today (v3.5.2), Wolfi Chromium, no shell, read-only
  root, restricted pod-security set, uid 1000.
- **JDownloader** runs on `ghcr.io/neilcar/jdownloader`: headless JDownloader
  on Java with **no desktop**. The owner reaches it through MyJDownloader only
  (owner's decision, as a trial). No shell, read-only root, restricted set,
  non-root.
- **The JDownloader version is fixed in the image** (owner's decision): the
  code (`JDownloader.jar`, `Core.jar`, plugins, `libs`, `extensions`) is part
  of the image and changes only when a new image is built. JDownloader's
  self-update is turned off.
- Both images private GHCR, cosign-signed (cosign 2.4.3, legacy referrers
  mode), covered by Kyverno `verify-neilcar-images`, built in CI on the ARC
  runners with native per-arch builds, Trivy-compared against the image they
  replace, new upstream versions arriving as watcher PRs.

## Non-goals

- No change to JDownloader's settings, download list, accounts, Event Scripter
  scripts, download folders or MyJDownloader device name.
- No change to FlareSolverr's URL, port (8191) or how Prowlarr calls it.
- No FlareSolverr version upgrade as part of the switch.
- Transmission stays as it is.

## Anti-goals (a failure even if it "works")

- **FlareSolverr less reliable than today** (owner's decision: "be as
  reliable"). Since its pod started (2026-11-02 16:09Z, ~9 hours of logs) the
  stock image hit Cloudflare's "Just a moment…" check 43 times and solved 42
  (one 60 s timeout), ~12 s per response on average, for ExtraTorrent (140
  grabs, the third most useful indexer) and PornRips. The new image must solve them
  as reliably before it replaces the old one, and stays only if it keeps doing
  so.
- **JDownloader settings or download list lost or rewritten** in a way the
  jlesage image can't read back. Going back must be a one-commit revert.
- **Downloads land somewhere new**, or the "download finished" webhook to n8n
  stops firing (Event Scripter, `jdownloader-trigger-n8n`), breaking the
  Erome scraper and downstream moves.
- JDownloader quietly updating its own code on the volume after the switch.

## Constraints (current state, 2026-11-02)

| App | Today's image | Deployed by | Runs on | Notes |
|---|---|---|---|---|
| FlareSolverr | `flaresolverr/flaresolverr:v3.5.2@sha256:c80ae007…` | arr chart (`fleet/arr/arr-values.yaml`, `flaresolverr:`) | mona (arm64) | Debian Chromium + Xvfb + patched chromedriver (undetected_chromedriver); `/config` emptyDir; 768Mi request; tailnet ingress `flaresolverr` (+ an old-name alias in `fleet/tailnet-old-names`) |
| JDownloader | `jlesage/jdownloader-2:v26.09.1` | `fleet/jdownloader` (pmoscode chart `jdownloader2` 1.12.0, takeOwnership) | amd2 (nodeSelector amd64) | Java 8 (IcedTea, Alpine); desktop on the web port behind `fleet/jdownloader-oauth2-proxy` at `jdownloader.goat-lizard.ts.net`; MyJD credentials from secret `jdownloader-myjd`; `Recreate` strategy |

JDownloader details:
- PVC `jdownloader-jdownloader2-data`: subPath `config` → `/config` (JD home:
  `cfg/` 188 files, `jd/`, `libs/`, `extensions/`, `tmp/`, `logs/`, jars,
  `build.json`), subPath `downloads` → `/output`. hostPath `/mnt/downloads` →
  `/complete`.
- Running build (`build.json`): JDownloaderRevision 50639, built 2026-10-28.
- Self-update is on today: `UpdateSettings` autoupdatecheck, silent install,
  install on exit, 10-minute interval.
- Event Scripter is enabled; its scripts live in
  `cfg/org.jdownloader.extensions.eventscripter.EventScripterExtension.scripts.json`
  (there is a `.bak-20261101`). The extraction extension is configured.
- n8n reacts to the webhook; nothing execs into the pod.

General:
- Kyverno `verify-neilcar-images` is Enforce; `apps` enforces the restricted
  set. Test every manifest change with the Kyverno CLI against every policy and
  PolicyException, using the rendered chart.
- Deploys through Fleet GitOps (lxdk8s main → deploy branch); merges with the
  owner's OK, after checks pass. arr-helm needs Read on any new package the arr
  chart pulls.

## Images (decided)

- **FlareSolverr goes into `neilcar/pyapps-image`** (my call): it is a Python
  app and that repo already has the publish, signing, Trivy, smoke-test and
  watcher machinery. Source: FlareSolverr's GitHub tag v3.5.2, Python deps
  pinned with hashes. Base: `distroless/python` plus Wolfi `chromium` (and
  what it needs to run: chromedriver, a virtual display if FlareSolverr needs
  one, fonts) — a `flaresolverr-base` in `neilcar/distroless` if the package
  list warrants it.
- **JDownloader gets its own private repo, `neilcar/jdownloader-image`** (my
  call, name included), same machinery as pyapps-image. Base: a
  `jdownloader-base` in `neilcar/distroless` with a Wolfi OpenJDK JRE (my
  call: the newest LTS JRE JDownloader runs on; Java 8 is not required) plus
  what JDownloader shells out to (ffmpeg for merging, the native 7-Zip binding
  for extraction).
- **The JDownloader snapshot**: JDownloader has no versioned releases, only
  its update servers. The build fetches the current JDownloader through its
  own updater in a build stage, records the revisions from `build.json` as the
  image's version, and copies the result into the image. The image is the
  version; the watcher opens a PR when the update servers have a newer
  revision.
- Trivy gate as before: nothing Critical/High in what we add; app images no
  worse than the vendor image they replace.

## JDownloader layout (decided)

- Code read-only in the image; state stays on the existing volume. The
  existing `/config/cfg` (settings, download list, accounts, scripts) is used
  as-is. Old code copies on the volume (`JDownloader.jar`, `Core.jar`, `jd/`,
  `libs/`, `extensions/`, `update/`, `java/`) are left in place, unused, so a
  revert to jlesage finds everything where it was.
- Self-update off **from the image side only** (my call): start options or a
  read-only overlay in the image, never an edit to `UpdateSettings` in the
  live `/config/cfg`, so a revert to jlesage gets its self-updating JDownloader
  back with no second step. The builder tests that JDownloader doesn't write
  the override back into `cfg`. If that proves impossible, `cfg` may be
  changed, and the revert runbook then includes re-enabling updates.
- MyJDownloader credentials keep coming from `jdownloader-myjd`; the device
  name stays the same so the owner's MyJDownloader sees the same device.
- Downloads keep going to `/output` and `/complete` exactly as today.
- **Updates are batched and automated** (owner's decision): the watcher
  checks the update servers once a week and opens one PR with the newest
  revision (plus any base-digest bump). That PR merges itself and rolls out
  through Fleet once the image's smoke tests pass (headless start against a
  fixture `cfg`, updates disabled, MyJD login path reached, Event Scripter
  loaded) — no owner OK needed for these PRs. A manual "rebuild now" dispatch
  takes the same path for a site that breaks between weekly runs. Cost: a
  site-plugin fix arrives up to a week later than today unless the rebuild is
  run by hand.

## Proof and switch-over (decided)

One app at a time: **FlareSolverr, then JDownloader**. Each switch is one
lxdk8s commit; reverting it restores the vendor image.

FlareSolverr:
- Before switching, run the new image as a second, temporary Deployment next
  to the old one on mona (my call) and send both the same requests: the
  ExtraTorrent and PornRips pages Prowlarr asks for, at least 20 each, spread
  over a few hours. The new image must solve every challenge the old one
  solves, in comparable time. Any extra failure means no switch.
- If Wolfi Chromium fails that test, FlareSolverr work stops there and goes
  back to the owner (owner's decision) with the results and the options
  (another browser build such as Debian Chromium or Chrome for Testing on the
  same base, or keeping the stock image). No fallback is planned or built up
  front. JDownloader carries on regardless.
- After the switch: Prowlarr's failed-query counts for ExtraTorrent and
  PornRips over the next day are no worse than before, and FlareSolverr's log
  shows challenges solved. Otherwise revert.
- Remove the temporary Deployment after the switch.

JDownloader:
- Before switching: copy `/config/cfg` to a dated backup on the volume.
- Checks, with the owner: MyJDownloader shows the device online with the
  existing download list; the owner adds a link and it downloads to the usual
  place; the "download finished" webhook reaches n8n; an archive extracts; no
  update check in the log. JDownloader's own log is read from the volume (no
  shell needed).
- While the trial runs, `fleet/jdownloader-oauth2-proxy` and its tailnet
  ingress stay deployed but have nothing to show; the chart's web Service is
  off or points nowhere (builder's call). If the owner keeps the new image,
  the proxy, ingress and the GitHub-login entry are removed in a follow-up
  commit. If not, the revert brings the desktop back.

## Left to the builder

- Whether FlareSolverr needs Xvfb (or runs Chromium truly headless) on Wolfi
  Chromium, and how undetected_chromedriver's patched-driver copy works under
  a read-only root (an emptyDir for its working directory is fine).
- Matching the stock image's Chromium flags and version line closely enough
  that Cloudflare treats it the same; the side-by-side test is the judge.
- The exact JDownloader start command, how its home is split between the
  image (code) and the volume (`cfg`, `logs`, `tmp`), and how updates are
  disabled (system properties vs settings files).
- Which JRE version; which ffmpeg/7-Zip pieces JDownloader actually loads.
- How the JDownloader chart is pointed at the new image and made to fit the
  restricted set, or whether plain manifests replace the chart.
- Smoke tests: FlareSolverr solving a local test page; JDownloader starting
  headless against a fixture `cfg` with updates disabled.
