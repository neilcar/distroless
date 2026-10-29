# Servarr apps on distroless — design

Status: reviewed, 2026-10-29.

## Why

Lidarr, Radarr, Prowlarr, Sonarr and Whisparr run third-party images
(linuxserver, hotio). They are the worst app images left in the cluster by
Trivy: Lidarr/Radarr/Prowlarr about 10 Critical and 120–140 High each,
Whisparr 10/66, Sonarr 0/37. Moving them onto our own distroless images, as
was done for SABnzbd and bandcampsync on 2026-10-28, removes nearly all of it.

## Goals

- One shared distroless base, `servarr-base`, in `neilcar/distroless`
  (apko/Wolfi, released packages only, Trivy-gated, cosign-signed with
  cosign 2.4.3 in legacy referrers mode), carrying only what the five .NET
  apps need: ICU, SQLite, CA certificates, tzdata, and `fpcalc`
  (chromaprint) for Lidarr. No shell.
- One new private repo, `neilcar/servarr-image`, building all five app images
  from each project's official release tarball, per architecture
  (amd64, arm64, native runners), private GHCR packages
  `ghcr.io/neilcar/{lidarr,radarr,prowlarr,sonarr,whisparr}`, tagged with the
  app version.
- Each image tested in CI before publishing: starts, answers its API, and runs
  against a copy of a real-shaped config folder (config.xml + SQLite DBs).
- The arr chart (`neilcar/arr-helm`) switches each app by an `images.yaml`
  change, and `update-images.py` follows new releases automatically, like
  SABnzbd.

## Non-goals

- No change to app data, settings, volumes or ports.
- Not moving other apps (beets, transmission, the GUIs).
- No self-update inside the apps (they already use `UpdateMechanism: Docker`).

## Anti-goals (a failure even if it "works")

- **An app down for days.** Owner's top concern. Every switch must be
  reversible in minutes, one app at a time.
- Touching or migrating app data in a way the old image can't read back.
- A different release channel than today's (see Constraints).

## Constraints (current state, 2026-10-28)

| App | Today's image | Branch | /config | Notes |
|---|---|---|---|---|
| Prowlarr | linuxserver 2.7.0.5723-ls166 | master | 184 MB | port 9696 |
| Radarr | linuxserver 6.4.4.10685-ls324 | master | 2.0 GB | port 7878 |
| Sonarr | linuxserver 4.0.20.3014-ls1 | main | 1.1 GB | port 8989 |
| Lidarr | linuxserver 3.1.6.5079-ls46 | master | 21 GB (covers) | ports 8686 (+8337 on the Service); uses `/usr/bin/fpcalc` |
| Whisparr | hotio v3-3.6.5-release.1886 | eros (v3) | 393 MB | port 6969; DB `whisparr3.db`; tarball bundles ffprobe |

- Each image follows the same branch the app is on today; versions start at
  the running version (no upgrade as part of the switch).
- Linuxserver pods run uid/gid 1000, `fsGroup` 1000, read-only root, with
  writable `/config`, `/run`, `/tmp`. Whisparr (hotio) runs as root today with
  no security context, but its files are already uid 1000.
- The new images run as uid 1000, read-only root, no shell. `PUID/PGID/UMASK`
  env stop mattering (no s6); TZ still applies.
- All config owned 1000:1000 already, so no chown step (unlike SABnzbd).
- Image signing: Kyverno `verify-neilcar-images` is Enforce.
- No container runtime on the owner's Mac; builds and tests run in CI
  (GitHub-hosted or the cluster's ARC runners).
- Deploys go through Fleet GitOps (lxdk8s), merges with the owner's OK.

## Switch-over (decided)

One app at a time, in this order: **Prowlarr, Radarr, Sonarr, Whisparr,
Lidarr** (least to most critical/largest).

**Mechanism (my call, from the builder check):** the trial and any rollback
use a per-app image override in lxdk8s `fleet/arr/arr-values.yaml`
(`<app>.image.repository/tag/digest`, plus the security-context change for
Whisparr in the same commit), not a chart release. One lxdk8s commit switches
one app; reverting that commit brings the old image back. That's minutes, with
no chart release and no unrelated image bumps riding along. After an app has run
cleanly for a day, its new image moves into the chart's `images.yaml` and the
override is removed (a no-op rollout). The chart is at 0.12.0 in Fleet.

**Versions during the rollout (my call):** before an app switches, its current
vendor image is pinned by digest in the override (freezing the linuxserver/hotio
auto-updates for that app), and the new image is built at exactly that app
version. So rollback is "the old vendor image, same version, same digest", and
the database never gets a newer schema than the old image can read. Automatic
version following for an app (servarr-image's release watcher and the chart's
`update-images.py`) is switched on only once that app has moved into
`images.yaml` after its clean day.

For each app:

1. Pin its current vendor image by digest in arr-values (no-op rollout).
2. Copy its `/config` databases and `config.xml` (not covers/logs) to a dated
   backup next to it.
3. Change the override to the new image (one lxdk8s commit); Fleet rolls it out.
4. Check: pod Ready, UI/API answers, a search or RSS sync runs, the download
   clients and indexers test green, and for Lidarr fpcalc works on an import.
5. If anything is off, revert that commit (minutes); the old image at the same
   version still works with the same data.
6. After a clean day: move the image into the chart's `images.yaml`, drop the
   override, enable auto-follow for it, and start the next app.

Whisparr's security context (uid 1000, read-only root, like the others; hotio
needed root and a writable root) changes in the same commit as its image, so
reverting that commit restores both.

## Trivy gate (my call, from the builder check)

The tarballs are self-contained .NET builds whose bundled NuGet assemblies we
can't change. So:
- **base layer** (`servarr-base`): strict, as for every distroless base: no
  Critical or High with a released fix;
- **app images**: no Critical or High in anything we add, and the app's own
  bundled findings must be no worse than the vendor image it replaces (compared
  in CI, as photoprism-index does). The bundled findings are listed in the
  release notes, not ignored silently.

## Left to the builder

- How the tarball is fetched and pinned (each app's servarr update API vs.
  GitHub releases; checksum pinning).
- Exact Wolfi package list for the base (and whether Whisparr's bundled
  ffprobe needs extra libs); a `-dev` variant if needed.
- The CI test fixtures (a config folder shaped like each app's), and how
  "answers its API" is checked without a real API key.
- Whether Lidarr's extra Service port 8337 needs anything (it is beets'
  web port on the same Service, not Lidarr).
- `update-images.py` patterns for the five tags.
