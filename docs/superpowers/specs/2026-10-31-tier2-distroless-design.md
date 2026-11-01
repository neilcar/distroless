# Tier 2 images on distroless (beets, Tautulli, SearXNG, threat-intel) — design

Status: reviewed (builder check), 2026-10-31.

## Why

After the Servarr move (2026-10-30), the third-party images left in the
cluster were ranked by exposure. Tier 2 is the set that is cheap to move:
Python apps that fit the existing `distroless/python` approach. Today they run
on linuxserver or upstream images with a shell, a package manager and (for
beets) a root s6 init that pip-installs plugins on every boot.

## Goals

- **Tautulli, SearXNG and beets** run on our own images: `ghcr.io/neilcar/
  {tautulli,searxng,beets}`, private GHCR, cosign-signed with cosign 2.4.3 in
  legacy referrers mode, no shell, uid 1000 (SearXNG keeps 977), read-only
  root, restricted pod-security set.
- **Threat-intel updater** (`fleet/tetragon-threatintel`, stdlib-only
  `update-policy.py`) moves from `python:3.12-slim` to
  `ghcr.io/neilcar/distroless/python`, so it falls under Kyverno
  verifyImages like every other neilcar image.
- **beets automation keeps working**: n8n Jobs and the owner still run
  `kubectl exec deploy/beets -c beets -- <entry point> …`. The bash entry
  points become Python (see beets below).
- New upstream versions arrive as watcher PRs, as in servarr-image.

## Non-goals

- No change to app data, settings, volumes, ports, ingress or URLs.
- No version upgrades as part of the switch: each image starts at the running
  version (Tautulli 2.18.2, beets 2.14.1, SearXNG 2026.10.19-81371861f).
- Not moving Tier 1 (transmission, PhotoPrism app, FlareSolverr,
  JDownloader), the databases, or Tier 4.
- The one-off `.sh` helpers in beets' `/config` (leftovers_run.sh,
  safe_stop.sh, beets.sh, fix_first_attempt.sh, remove_stale_locked.sh …)
  are not ported. Owner agreed they stop working.

## Anti-goals (a failure even if it "works")

- **A nightly beets import, downloads import or review Apply silently lost or
  half-done.** The run-lock, attach/re-attach and exit-code behaviour the n8n
  Jobs depend on must be identical.
- beets' library DB (`musiclibrary.blb`) or `state.pickle` changed in a way
  the old image can't read back.
- An app down for days: every switch is one revertable lxdk8s commit.

## Constraints (current state, 2026-10-31)

| App | Today's image | Deployed by | Run as | Notes |
|---|---|---|---|---|
| Tautulli | linuxserver 2.18.2-ls250 | `fleet/tautulli` (plain manifests via Fleet) | 1000, ro root | already starts `/lsiopy/bin/python3 /app/tautulli/Tautulli.py --datadir /config --nolaunch --port 8181`, no s6 |
| SearXNG | ghcr.io/searxng/searxng:2026.10.19-81371861f | `fleet/searxng/searxng.yaml` | 977, ro root | settings.yml ConfigMap (subPath), `SEARXNG_SECRET` from Infisical, writes only `/tmp` |
| beets | linuxserver 2.14.1-ls358 + mods `neilcar/docker-mods:beets-extend`, `beets-httpshell` | arr chart (`fleet/arr/arr-values.yaml`, `beets:`) | root init → `abc` (1000), writable root | `beet web` on 8337 (arr-report reads it); httpshell on 5555 |
| threat-intel | python:3.12-slim (digest) | `fleet/tetragon-threatintel/cronjob.yaml` | 65534, ro root | `python3 /opt/updater/update-policy.py`, stdlib + ssl |

beets details:
- Plugins (config.yaml): fetchart embedart convert scrub replaygain lastgenre
  chroma web fromfilename lastimport musicbrainz bandcamp.
- Python packages in use: beets 2.14.1, beetcamp 0.26.0, beets-alternatives,
  beets-extrafiles 0.0.7, python3-discogs-client, pylast, pyacoustid, Flask,
  flask-cors, Pillow, langdetect, mutagen, requests, requests-ratelimiter,
  beautifulsoup4. Today the beets-extend mod's only action (its one
  cont-init script) is `pip install -U beets-alternatives beetcamp` at every
  boot; the image pins them instead. beets-alternatives, beets-extrafiles and
  discogs-client are installed but their plugins are not enabled, so the image
  leaves them out (my call; adding one back is a requirements line).
- Binaries used: `ffmpeg`, `fpcalc`, `flac`, `metaflac`, ImageMagick
  `convert`, `mp3val`.
- Ownership: `/config` all 1000:1000; `/bandcamp` 1000:1000; `/music/music`
  1026:100 and `/downloads` 911:1001 on NFS, already written as uid 1000
  today. So uid 1000 needs no chown.
- The httpshell mod has no callers (no requests in a week of logs, no
  references in any repo). It is dropped, with its Service port.
- The admission policy in `beets-auto-import/k8s/beets-auto-import.yaml` pins
  the exact exec args for three Job kinds (auto, downloads, review); the n8n
  builders (`n8n/build_workflow.py`, `build_downloads_workflow.py`,
  `build_review_workflows.py`) generate those args.

General:
- Kyverno `verify-neilcar-images` is Enforce; the apps/searxng namespaces
  enforce the restricted set. Test any manifest change with the Kyverno CLI
  against every policy and PolicyException.
- Builds and tests run in CI (ARC runners, native per-arch matrix); deploys go
  through Fleet GitOps; merges with the owner's OK, after checks pass.
- Don't restart n8n without asking (an n8n workflow re-import may be needed).

## Images (decided)

- **One new private repo, `neilcar/pyapps-image`** (my call, name included),
  building `tautulli`, `searxng` and `beets` from per-app Dockerfiles, using
  the servarr-image machinery: per-app publish keyed on its inputs,
  cosign sign + `cosign verify` pinned to `build.yml@refs/heads/main`, Trivy
  compare against the image it replaces, smoke tests, daily watcher opening
  one PR per app version and weekly base-digest PRs, release notes with
  earlier builds.
- Sources: Tautulli and SearXNG from their GitHub source at the running
  tag/commit; beets and its plugins from PyPI with hashes (my call: pinned
  `requirements.txt` with `--require-hashes`).
- Bases: Tautulli and SearXNG on `distroless/python`. beets gets a
  **`beets-base`** in `neilcar/distroless` (apko/Wolfi, like `sabnzbd-base`)
  adding ffmpeg, chromaprint (`fpcalc`), flac, imagemagick; `mp3val` is not
  in Wolfi and is built from source in the beets Dockerfile (checksum-pinned),
  as sabnzbd-image does for par2/unrar.
- Trivy gate as for servarr: strict on the base; app images no worse than the
  vendor image they replace, nothing Critical/High in what we add.

## beets entry points (decided)

The seven bash scripts in `beets-auto-import/beets/` become Python
(stdlib only: `fcntl.flock`, `os.setsid`/`subprocess`, `os.kill`, `/proc` for
pgrep, `pathlib`/`shutil` for find/mv/rm): `beets_auto_import.sh`,
`import_downloads.sh`, `review.sh`, `repair_and_rerun.sh`,
`restart_stopped_run.sh`, `resume_downloads.sh`, `unroot_untagged_locked.sh`.

- Same arguments, same lock file (`/config/auto-import/run.lock`), same run
  directories and logs, same exit codes (the Jobs' podFailurePolicy fails on
  auto 10/11, downloads 2/10), same "attach re-attaches to the running run"
  behaviour.
- They run as the image's `python3 /config/auto-import/<name>.py`; the
  admission policy's `execPrefix + [...]` lists and the three n8n builders
  change to the new argv in the same beets-auto-import PR.
- Order: the Python entry points ship **first, on the current linuxserver
  image** (it has python3), so the automation is proven before the image
  changes. The image switch is then a pure image change.
- Proven means (my call): three clean nightly auto runs, at least one
  downloads import with a path argument, one review export + Apply, and unit
  tests for the lock and re-attach paths (including a dropped exec stream).
  Tautulli, SearXNG and threat-intel may switch meanwhile; beets waits.
- Re-importing the changed n8n workflows is part of this work (after the
  owner OKs the beets-auto-import PR); restarting n8n is not, and is asked
  for separately if it turns out to be needed.

## Switch-over (decided)

One app at a time: **threat-intel, Tautulli, SearXNG, beets**. Each is one
lxdk8s commit (image + any security-context change together); reverting it
restores the old image. Before beets switches: copy `musiclibrary.blb`,
`state.pickle` and `config.yaml` to a dated backup in `/config`.

Checks per app:
- threat-intel: next hourly run succeeds and re-renders the TracingPolicy.
- Tautulli: UI loads, Plex websocket connected, history page shows recent plays.
- SearXNG: `/healthz`, a JSON search returns results.
- beets: `beet web` answers on 8337 (arr-report run is green), one nightly
  auto-import and one downloads import complete, review export + an Apply
  work, `beet` by hand works, fpcalc/ffmpeg/convert run on an import.

After a clean day, the arr chart gets beets in `images.yaml` (like the
Servarr apps) and auto-follow is turned on: beets and plugin version bumps follow automatically after the chart's cooldown, like the Servarr apps (owner's decision). As a guard (my call), pyapps-image's beets build runs the beets-auto-import unit tests and a `beet` import smoke test inside the new image before it publishes, so a release that breaks the scripts never reaches the chart; Tautulli and
SearXNG digests reach lxdk8s as PRs opened by pyapps-image's release workflow
with the existing `neilcar-homelab` GitHub App (as arr-helm already does for
the arr chart; my call). Those PRs wait for the owner's OK like every merge.

## Cleanup (decided)

Delete the completed Job `apps/stash-library-move-path-rewrite` (the 10-28
one-off on `alpine:3.20.3`). Nothing to port.

## Left to the builder

- How SearXNG is served (its upstream image uses granian) and which of its
  build steps (static assets, translations) run at build time.
- Tautulli's bundled `lib/` vs pip deps; whether its git-based self-update
  needs switching off in config (it must not try to update).
- The `beets-base` package list, and whether a `-dev` variant is needed for
  building wheels (Pillow, etc.).
- Test fixtures (a small beets library + config, a Tautulli datadir, a
  SearXNG settings.yml) and how the smoke tests drive them.
- Watcher sources: Tautulli GitHub releases, SearXNG commits/tags, beets
  PyPI; whether beets plugins follow automatically or by hand.
- Unit tests for the ported entry points, especially lock and attach paths.
