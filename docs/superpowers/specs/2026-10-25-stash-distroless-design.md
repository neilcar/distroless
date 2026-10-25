# Distroless Stash image — design

Status: for owner review, 2026-10-25. Spans `neilcar/distroless` (a new `stash-base`
image) and a new repo `neilcar/stash-image` (builds Stash from source onto it), plus the
Fleet values in `neilcar/lxdk8s` (`fleet/arr/arr-values.yaml`).

## Intent

Stash (`stash-app` in namespace `apps`) runs the upstream `docker.io/stashapp/stash:v0.31.1`
(Alpine 3.23.3). Trivy reports 13 Critical / 78 High / 44 Medium / 6 Low. About 40 of
the Critical/High come from Alpine's `openexr*` packages that ffmpeg drags in, and 7 are
Go standard-library findings compiled into the Stash binary. The owner wants Stash on
their own distroless Wolfi base, like the other images they've moved: pinned released
packages, no package manager, no shell, rebuilt automatically, with far fewer findings.

The owner watches in a browser through Stash's web player, typically before bed and on
Sunday afternoons; scheduled jobs index new content.

## Goals

1. **`stash-base` in `neilcar/distroless`**, built with the same pipeline as the other
   images (catalog entry, `dl sync` locks, released-only versions, Trivy gate, cosign,
   SBOM, reproducible digests):
   - ffmpeg and ffprobe (Wolfi; ffmpeg 9.0 today, which pulls in no `openexr`);
   - a Python 3.12 runtime answering to both `python` and `python3` (plugins call both);
   - Python libraries the current image ships and the installed scrapers/plugins use:
     from Wolfi `py3.12-requests`, `py3.12-requests-toolbelt`, `py3.12-lxml`,
     `py3.12-beautifulsoup4`, `py3.12-pip` (and their dependencies: certifi, idna,
     urllib3, charset-normalizer, soupsieve, packaging, pyparsing, setuptools); not in
     Wolfi and pinned by version and sha256 from PyPI: `cloudscraper`, `mechanicalsoup`,
     `stashapi` (all pure Python);
   - CA certificates, tzdata. amd64 and arm64 (the pod is pinned to amd64 today, but the
     base is built for both like the others).
2. **`neilcar/stash-image`** (new, public, like `distroless`): builds Stash **from source**
   (owner's decision) at an upstream **release tag** with the current Go and the UI
   (frontend) build, and copies the binary onto `stash-base`. Publishes
   `ghcr.io/neilcar/stash` signed, with SBOM, tag = Stash version plus a build suffix.
3. **Automatic upgrades** (owner's decision): when Stash publishes a new release (or
   `stash-base` gets a new digest), CI builds the new image, runs the checks below, and
   opens a PR on `neilcar/lxdk8s` (into `main`) bumping the `stash` image tag and digest
   in `fleet/arr/arr-values.yaml`. The owner merges; the existing render check promotes
   `main` to `deploy`; Fleet deploys. Every release gets a PR; its body says whether the
   release migrates the database (the owner's merge is the gate). Credential: a
   fine-grained PAT created by the owner, scoped to `neilcar/lxdk8s` only, Contents and
   Pull requests read/write, stored as secret `LXDK8S_PR_TOKEN` in `neilcar/stash-image`
   by the owner (`gh secret set`), never handled by the builder.
4. **Same runtime contract as today:** uid/gid 1000 (`runAsUser`/`runAsGroup` in the
   chart), `HOME=/config`, `STASH_CONFIG_FILE=/config/config.yml`, `STASH_PORT=9998`,
   `USER=stash`, the same volumes (`/config`, `/pr0n`, `/public`, `/complete`,
   `/public/downloads`), the chart's liveness/readiness probes, the 8 GiB limit. The
   existing database, generated files and config are used as they are.

## Must keep working (the owner's failure conditions)

Any of these breaking makes the switch a failure even if the findings drop:

- **Live transcoding in the browser player** (the owner: "transcoding has to work"):
  playing a file whose codec the browser can't play directly must transcode on the fly
  (hardware acceleration is off; software ffmpeg).
- **The scheduler plugin** (`stash-scheduler`, `python3 …/stash_scheduler.py`) that runs
  the scans which pick up new content.
- **Scrapers** used to tag new scenes: 153 of the 811 installed community scrapers run
  Python.
- The other enabled Python plugins: `PythonDepManager` (pip-installs plugin dependencies
  at runtime, into the user site under `HOME=/config`), `date_parser`,
  `stashdb-performer-gallery`, `tagScenesWithPerfTags`; and the JS plugin
  `filenameParser`.

## Success criteria

1. CI smoke tests, in the built image, with no shell: Stash starts and serves the UI and
   GraphQL on 9998; a scan of a small sample library completes; a live-transcode request
   for an HEVC (or other non-browser) sample returns playable video; ffprobe reads the
   samples; `python` and `python3` import every library in Goal 1; the stash-scheduler
   plugin and one Python scraper run end to end against fixtures.
2. After the switch, on the real pod: the owner's library loads, a browser plays a file
   that needs transcoding, the next scheduled scan runs, a scrape works.
3. Trivy C/H/M/L lower than v0.31.1's (`docker.io/stashapp/stash:v0.31.1@sha256:df744af5…`),
   compared with the same database.
4. No shell in the published image.

## Non-goals

- `stash-gen` (the `python3 /work/gen_worker.py` preview-generation Job) keeps its
  current image (owner's decision), as do the Alpine helper Jobs
  (`stash-db-quick-check`, `stash-pr0n-libraries`).
- Hardware-accelerated transcoding, DLNA, and other players.
- The disabled plugins (AIOverhaul, LocalVisage, ai_tagger, star_identifier, filemonitor,
  stashai, visage, PythonToolsInstaller, MRStashTranscode) need not work; enabling one
  later may need extra libraries.
- Changing the chart beyond the image (the chart's `PUID`/`PGID`/`UMASK` env, used by the
  upstream image's entrypoint, becomes inert and may stay).

## Anti-goals

- A shell or busybox in the runtime image.
- Pre-release Stash versions or Go/Node toolchains (release tags only).
- A silent break of any "must keep working" item.
- Changes to `photoprism-base` (another project depends on it).
- Manual `helm upgrade`: deployment stays Fleet GitOps.

## Constraints and context

- Deployed by Fleet bundle `homelab-apps-fleet-arr` from `lxdk8s` `fleet/arr`
  (chart `oci://ghcr.io/neilcar/charts/arr` 0.9.0, values `arr-values.yaml`, section
  `stash:`), nodeSelector amd64.
- The upstream image runs Stash via its own entrypoint; the pod sets
  `runAsUser: 1000`, `runAsNonRoot: true`, and `HOME=/config` because uid 1000 has no
  passwd entry. The new image runs `stash` directly as its entrypoint.
- Stash's binary embeds the UI; the build needs Go and Node/yarn at the versions Stash's
  release declares (or newer released ones). The distroless repo's `-dev` variants or a
  Wolfi build stage may be used for building; the runtime is `stash-base`.
- `distroless` conventions apply: released-only Wolfi versions, `.trivyignore` owner-only,
  notify on main only, CI-made commits, packages re-signed per run. Commit trailers per
  each repo's rules.
- PhotoPrism maintenance pauses Stash batch Jobs; nothing here changes that.

## Calls made in design (controller's, after the builder check)

- Python libraries: audit the imports of the enabled plugins and the 153 Python scrapers
  and add anything pure-Python they need beyond Goal 1, pinned; PythonDepManager covers
  the rest at runtime (nothing is installed in `/config/.local` today, so no musl-built
  wheels carry over).
- ffmpeg: a smoke check compares the encoder/decoder set with today's image (libx264,
  libx265, libvpx/libvpx-vp9, libopus, aac, libwebp at least); a missing one blocks.
- Shell: audit the enabled plugins and Python scrapers for `sh`/`os.system`/
  `subprocess(shell=True)`/external tools; if an enabled one needs a shell, stop and ask
  the owner.
- Fixtures: synthetic ffmpeg-generated clips (incl. HEVC for the transcode test); the
  scraper test runs offline against a local fixture server.
- Trivy: same rule as the owner's other switches — no severity higher than v0.31.1's and
  the total lower, same Trivy DB for both.
- Rollback: v0.31.1 built from source has v0.31.1's schema, so no migration; copy the
  sqlite DB before the switch; rollback = restore the upstream image line in the values.

## Left to the builder

- How the three non-Wolfi Python packages get in (a vendor-layer kind for wheels, a
  melange package, or a pip install in a build stage copied into site-packages), as long
  as they're pinned by version and sha256 and the runtime has no shell.
- Whether `python` is a symlink in the image or provided by the launcher.
- The `stash-image` CI layout, how releases are detected (GitHub releases API on a
  schedule, or Renovate/Dependabot), and the PR mechanics on `lxdk8s`.
- Test fixtures (small sample videos and a sample library), pinned by sha256.
- Whether to also publish arm64 Stash builds (the base is multi-arch; the app may be
  amd64-only if the UI build makes arm64 slow).
