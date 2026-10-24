# Distroless Base Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public repo `neilcar/distroless` that assembles pinned, released-only, multi-arch distroless images (`static`, `python` for every supported line, `nginx` stable + mainline) from Wolfi packages, keeps them updated automatically behind a Trivy gate, publishes them signed with SBOMs to public GHCR, and moves four consumer repos onto them with a measured vulnerability reduction.

**Architecture:** A small Python tool (`dl`) is the brain: it reads the Wolfi APKINDEX for both arches and endoflife.date, decides which lines exist and what each line's newest *released* version is, renders one `apko` config per image/line/variant into `locks/`, and the workflows run `apko lock` / `apko build`, Trivy, the gate, `crane` push, and `cosign`. A scheduled `sync` workflow commits changed locks to `main`; a `build` workflow builds/scans/gates/publishes whatever changed; a `rescan` workflow re-scans published images daily. Every decision function is pure and unit-tested offline against fixtures.

**Tech Stack:** Python 3.12 + `uv` + `pytest` + `ruff` (tooling only), `apko` and `melange` (pinned release binaries, verified by checksum), Wolfi (`https://packages.wolfi.dev/os`), Trivy, `crane`, `cosign` (keyless, GitHub OIDC), GitHub Actions, GHCR, `gh` CLI for issues.

**Spec:** `docs/superpowers/specs/2026-10-24-distroless-base-images-design.md`

## Global Constraints

- Repo `neilcar/distroless`, **public**; images `ghcr.io/neilcar/distroless/{static,python,nginx}`, **public** packages.
- Packages come only from Wolfi (`https://packages.wolfi.dev/os`, key `https://packages.wolfi.dev/os/wolfi-signing.rsa.pub`) plus this repo's own config-only melange package. **Never** use `cgr.dev/chainguard/*` images anywhere, including build stages and CI.
- **Only released versions**, for every package in every image (transitive deps included): reject any version containing `_git`, `_alpha`, `_beta`, `_rc`, `_pre`, `_p` snapshot suffixes (`_git` is the one seen today). Newer `-rN` revisions of a released version are allowed.
- Python lines: every cycle endoflife.date reports as released and not past EOL, that has a released Wolfi build of `python-<cycle>` on **both** x86_64 and aarch64. Expected today: 3.11, 3.12, 3.13, 3.14, 3.15. nginx lines: `stable` (`nginx-stable`) and `mainline` (`nginx-mainline`). static: one line, `latest`.
- Arches: `linux/amd64` and `linux/arm64` for every image.
- Runtime images: no shell, no package manager, non-root user `nonroot` uid/gid **65532**. `-dev` variants (python only) add `busybox`, `py3.<minor>-pip`, `uv`.
- nginx base: listens on **8080**, pid and temp paths under `/tmp`, serves `/usr/share/nginx/html`, includes `/etc/nginx/conf.d/*.conf`; default server lives in `/etc/nginx/conf.d/default.conf` so consumers can replace it.
- Scan gate: block on any Critical/High **with a fixed version** not listed in `.trivyignore`; block if the candidate has more findings than the currently published image at any severity; first publish of a line has only the first rule. `.trivyignore` is edited only by the owner; automation never writes to it.
- The bytes that were scanned are the bytes that get pushed: pushed digest must equal the scanned OCI index digest, or the job fails before signing.
- Every published image: `cosign sign` (keyless) + `cosign attest --type spdxjson` with the apko SBOM.
- Notifications are GitHub issues in `neilcar/distroless`, upserted by title (one open issue per title), label `automation`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Ask the owner before pushing to or merging in any consumer repo, and before rolling trakt-clean out on the cluster.

## Review Focus

1. **A transitive package in a lock resolves to a snapshot** (`_git`) even though the headline pin is released → `dl lock-check` must fail the sync for that line and open an issue, not commit it. (Task 2, `test_lockcheck_rejects_transitive_snapshot`.)
2. **A line exists on one arch only** (Wolfi published aarch64 late) → the line is not added yet and is not an error. (Task 3, `test_line_needs_both_arches`.)
3. **endoflife.date is unreachable or returns junk** → sync keeps the current set of Python lines unchanged and opens an issue; it never mass-removes lines. (Task 3, `test_eol_fetch_failure_keeps_current_lines`.)
4. **First publish of a new line** (no published image to compare) → only the fixed-Critical/High rule applies; the job must not crash on a missing image. (Task 5, `test_gate_first_publish`.)
5. **Rescan finds a new Critical with no fix available** → issue only, no rebuild trigger (a rebuild can't help and would loop daily). (Task 7, `test_rescan_unfixed_opens_issue_without_rebuild`.)

---

## File Structure

```
distroless/
  README.md                         # what the images are, tags, how consumers pin, how automation behaves
  catalog.yaml                      # image definitions (packages per variant, user, entrypoint/cmd, line source)
  .trivyignore                      # owner-only exceptions (starts empty with a header comment)
  pyproject.toml / uv.lock          # tooling package `dltools`, console script `dl`
  src/dltools/
    wolfi.py                        # APKINDEX parsing, release filter, newest released version per arch
    lines.py                        # supported line discovery (python via endoflife.date, nginx fixed, static)
    render.py                       # catalog + line + pins -> apko config dict
    lockcheck.py                    # validate an apko lock file is released-only and dual-arch
    tags.py                         # tag list for image/line/variant/version/lock hash
    gate.py                         # Trivy JSON (+ published JSON) + ignore list -> GateResult
    rescan.py                       # per-image rescan decision (issue? rebuild?)
    state.py                        # read/write state/lines.json, diff old vs new -> events
    notify.py                       # upsert GitHub issue via gh
    cli.py                          # `dl sync|lock-check|matrix|tags|gate|rescan-decide`
  tests/ (fixtures/ APKINDEX excerpts, eol json, trivy json, lock json)
  melange/nginx-config.yaml         # config-only package `distroless-nginx-config`
  melange/nginx-config/{nginx.conf,default.conf}
  state/lines.json                  # written by `dl sync`
  locks/<image>/<line>/<variant>.apko.yaml   # rendered by `dl sync`
  locks/<image>/<line>/<variant>.lock.json   # written by `apko lock`
  .github/workflows/{ci,sync,build,rescan}.yml
  .github/dependabot.yml            # github-actions updates for this repo
```

`variant` is `runtime` or `dev`. Line names: python `3.11`…, nginx `stable`/`mainline`, static `latest`.

---

### Task 1: Repo bootstrap and Wolfi index parsing

**Files:**
- Create: `pyproject.toml`, `src/dltools/__init__.py`, `src/dltools/wolfi.py`, `tests/test_wolfi.py`, `tests/fixtures/APKINDEX.x86_64`, `tests/fixtures/APKINDEX.aarch64`, `.github/workflows/ci.yml`, `.gitignore`, `README.md` (stub), and move the spec + this plan into the repo.

**Interfaces:**
- Produces:
  - `parse_apkindex(text: str) -> dict[str, list[str]]` — package name → all versions.
  - `is_released(version: str) -> bool`
  - `newest_released(index: dict[str, list[str]], package: str) -> str | None` — newest by apk version ordering among released versions.
  - `newest_released_all_arches(indexes: dict[str, dict[str, list[str]]], package: str) -> str | None` — newest released version present in **every** arch index.
  - `fetch_index(arch: str) -> str` (`arch` ∈ `x86_64`, `aarch64`; downloads and untars `APKINDEX.tar.gz`).
  - `upstream_version(version: str) -> str` — strips `-rN` (`"3.12.15-r6"` → `"3.12.15"`).

- [ ] **Step 1:** `gh repo create neilcar/distroless --public --description "Distroless base images assembled from pinned Wolfi packages"`; `git init` in `/Users/rando/code/home/distroless`, add remote; commit the existing `docs/` (spec + plan).
- [ ] **Step 2: Write failing tests** in `tests/test_wolfi.py`, fixtures trimmed from the real 2026-10-24 index (python-3.13 has `3.13.15-r8` and `3.13.16_git20261016-r2`; python-3.15 has `3.15.0-r0` and `3.15.0_git20261017-r4`; one package present only in x86_64):
  - `test_is_released`: `is_released("3.12.15-r6")`, `is_released("1.30.2-r0")` true; `"3.13.16_git20261016-r2"`, `"3.15.0_rc1-r0"`, `"1.0_alpha2-r0"`, `"2.0_beta1-r0"`, `"2.0_pre1-r0"` false.
  - `test_newest_released_skips_snapshot`: python-3.13 → `"3.13.15-r8"`.
  - `test_newest_released_prefers_higher_revision`: given `3.12.15-r5`, `3.12.15-r6` → `"3.12.15-r6"`.
  - `test_version_ordering_is_apk_not_lexical`: `3.12.9-r0` < `3.12.15-r0`; `1.30.10-r0` > `1.30.2-r9`.
  - `test_newest_released_all_arches_requires_both`: package only in x86_64 → `None`.
  - `test_upstream_version`.
- [ ] **Step 3:** Run `uv run pytest tests/test_wolfi.py -v` → FAIL (module missing).
- [ ] **Step 4:** Implement `wolfi.py`. Use apk version comparison semantics (numeric segments, then `_suffix`, then `-rN`); implement a small comparator rather than pulling a dependency.
- [ ] **Step 5:** Run tests → PASS. Add `ci.yml` (on PR and push: `uv sync`, `uv run ruff check`, `uv run pytest`). Commit.

### Task 2: Lock validation

**Files:** Create `src/dltools/lockcheck.py`, `tests/test_lockcheck.py`, `tests/fixtures/lock-*.json`.

**Interfaces:**
- Consumes: `is_released` (Task 1).
- Produces: `check_lock(lock: dict, required_arches: set[str] = {"x86_64", "aarch64"}) -> list[str]` — human-readable violations, empty when OK. Reads the apko lock format (`contents.packages[]` with `name`, `version`, `architecture`).

- [ ] **Step 1: Failing tests:**
  - `test_lockcheck_clean_lock_ok` → `[]`.
  - `test_lockcheck_rejects_transitive_snapshot`: lock where `python-3.13` is released but `libexpat1` is `2.7.4_git20261001-r0` → one violation naming `libexpat1` and its version.
  - `test_lockcheck_requires_both_arches`: lock with only x86_64 packages → violation mentioning `aarch64`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 3: Line discovery and state

**Files:** Create `src/dltools/lines.py`, `src/dltools/state.py`, `tests/test_lines.py`, `tests/test_state.py`, `tests/fixtures/python-eol.json`.

**Interfaces:**
- Consumes: `newest_released_all_arches` (Task 1).
- Produces:
  - `@dataclass Line(image: str, name: str, package: str, version: str)` — `version` is the full Wolfi version of the headline package (`"3.12.15-r6"`); for static, `package="ca-certificates-bundle"`.
  - `python_lines(eol: list[dict], indexes, today: date) -> list[Line]` — cycle supported if `releaseDate <= today` and (`eol` is `false` or `eol > today`) and `newest_released_all_arches(indexes, f"python-{cycle}")` is not `None`.
  - `nginx_lines(indexes) -> list[Line]` — `stable`→`nginx-stable`, `mainline`→`nginx-mainline`.
  - `static_lines(indexes) -> list[Line]` — single line `latest`.
  - `discover(indexes, eol: list[dict] | None, today: date, current: list[Line]) -> tuple[list[Line], list[str]]` — returns lines and warnings; when `eol is None` (fetch failed / invalid JSON / empty list) the python lines are **copied from `current`** (versions still refreshed from the index if possible) and a warning is returned.
  - `load_state(path) -> list[Line]`, `save_state(path, lines)`, `diff(old, new) -> list[Event]` with `Event(kind: Literal["line_added","line_removed","version_changed","nginx_minor_changed"], line: Line, detail: str)`. `nginx_minor_changed` fires when `stable`/`mainline` moves to a new `major.minor` (e.g. 1.30.x → 1.32.x), so the owner hears consumers on `nginx:1.30` stop updating.
- [ ] **Step 1: Failing tests** (fixture eol JSON from endoflife.date shape `{"cycle","releaseDate","eol"}`; today = 2026-10-24):
  - `test_python_lines_expected_today` → names `["3.11","3.12","3.13","3.14","3.15"]`, `3.13` version `"3.13.15-r8"`, `3.15` version `"3.15.0-r0"`.
  - `test_python_line_eol_excluded` (3.10 with eol 2026-10-31 and today 2026-11-01 → excluded).
  - `test_python_unreleased_cycle_excluded` (cycle with future releaseDate).
  - `test_line_needs_both_arches`.
  - `test_eol_fetch_failure_keeps_current_lines` (`eol=None`, current has 3.11–3.15 → same names returned, one warning).
  - `test_diff_events` (added, removed, version_changed, nginx_minor_changed each produced once).
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** PASS → **Step 5:** commit.

### Task 4: Catalog, rendering, tags, and the `dl sync` command

**Files:** Create `catalog.yaml`, `src/dltools/render.py`, `src/dltools/tags.py`, `src/dltools/cli.py`, `tests/test_render.py`, `tests/test_tags.py`, `tests/test_cli_sync.py`.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `catalog.yaml` keys per image: `packages` (by variant; `{line}` / `{minor}` placeholders, e.g. `python-{line}`, `py{line}-pip`), `accounts` (nonroot 65532), `entrypoint`/`cmd`, `paths` (writable dirs), `extra_repositories` (nginx: the local melange repo).
  - `render(catalog: dict, line: Line, variant: str) -> dict` — apko config: `contents.repositories` = Wolfi (+ local repo for nginx), `contents.keyring`, `contents.packages` = catalog packages with the headline package pinned as `name=version`, `accounts`, `entrypoint`, `cmd`, `archs: [x86_64, aarch64]`, `annotations` incl. `org.opencontainers.image.source: https://github.com/neilcar/distroless`.
  - `tags(line: Line, variant: str, lock_hash: str) -> list[str]` — python runtime: `["3.12", "3.12.15", "3.12.15-<hash8>"]`; dev: same with `-dev` suffix (`"3.12-dev"`, `"3.12.15-dev"`, `"3.12.15-<hash8>-dev"`); nginx: `["stable", "1.30", "1.30.2", "1.30.2-<hash8>"]`; static: `["latest", "<hash8>"]`. `lock_hash` = sha256 of the lock file bytes.
  - `dl sync --state state/lines.json --locks locks/ [--today YYYY-MM-DD]`: fetch indexes + eol, `discover`, write `state/lines.json`, write `locks/<image>/<line>/<variant>.apko.yaml` for every current line/variant, delete dirs for removed lines (published images stay), print events as JSON lines to stdout and warnings to stderr. Locks themselves are produced by the workflow (`apko lock`) because they need the apko binary.
- [ ] **Step 1: Failing tests:**
  - `test_render_python_runtime_has_no_shell_or_apk` — packages contain `python-3.12=3.12.15-r6`, `ca-certificates-bundle`, `tzdata`, `wolfi-baselayout`; contain none of `busybox`, `apk-tools`, `bash`; user uid 65532; `archs == ["x86_64","aarch64"]`.
  - `test_render_python_dev_adds_tools` — adds `busybox`, `py3.12-pip`, `uv`.
  - `test_render_nginx_uses_local_config_package` — packages include `nginx-stable=1.30.2-r0` and `distroless-nginx-config`, repositories include the local repo path, cmd runs nginx in foreground.
  - `test_render_static_minimal` — exactly `wolfi-baselayout`, `ca-certificates-bundle`, `tzdata`.
  - `test_tags_*` for python runtime/dev, nginx, static (values above).
  - `test_cli_sync_writes_state_and_configs` — with fixture indexes/eol injected (monkeypatch `fetch_index`/eol fetch), produces `locks/python/3.12/runtime.apko.yaml`, `locks/python/3.12/dev.apko.yaml`, nginx `stable`/`mainline`, static `latest`; second run with no changes emits no events and leaves files byte-identical.
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** PASS → **Step 5:** commit.

### Task 5: Scan gate

**Files:** Create `src/dltools/gate.py`, `tests/test_gate.py`, `tests/fixtures/trivy-*.json`, `.trivyignore`.

**Interfaces:**
- Produces:
  - `load_ignore(path) -> set[str]` (Trivy ignore file: IDs, `#` comments, blank lines).
  - `@dataclass GateResult(passed: bool, reasons: list[str], candidate_counts: dict[str,int], published_counts: dict[str,int] | None)`
  - `evaluate(candidate: dict, published: dict | None, ignore: set[str]) -> GateResult` — input is Trivy `--format json` output (`Results[].Vulnerabilities[]` with `VulnerabilityID`, `Severity`, `FixedVersion`). Ignored IDs are dropped first. Rule 1: any `CRITICAL`/`HIGH` with non-empty `FixedVersion` → fail. Rule 2 (only when `published` is not None): any severity where candidate count > published count → fail. Multi-arch: called once per arch; the workflow fails if either fails.
  - `dl gate --candidate c.json [--published p.json] --ignore .trivyignore` → prints a Markdown summary table (severity × candidate/published) and exits 1 on fail.
- [ ] **Step 1: Failing tests:** `test_gate_passes_clean`; `test_gate_blocks_fixable_high`; `test_gate_allows_unfixed_high_when_not_worse`; `test_gate_blocks_worse_than_published` (Medium 3 vs 2); `test_gate_respects_ignore`; `test_gate_first_publish` (published None, unfixed High present → pass).
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** PASS → **Step 5:** commit. `.trivyignore` starts with a header comment saying only the owner edits it.

### Task 6: nginx config package and image smoke tests

**Files:** Create `melange/nginx-config.yaml`, `melange/nginx-config/nginx.conf`, `melange/nginx-config/default.conf`, `tests/smoke/test_images.sh`.

**Interfaces:**
- Produces: package `distroless-nginx-config` (version `1.0.0-r0`, arch-independent content, built for both arches) installing `/etc/nginx/nginx.conf` and `/etc/nginx/conf.d/default.conf`. `nginx.conf`: no `user` directive, `pid /tmp/nginx.pid`, `client_body_temp_path`/`proxy_temp_path`/`fastcgi_temp_path`/`uwsgi_temp_path`/`scgi_temp_path` under `/tmp`, `error_log stderr`, `access_log /dev/stdout`, `include /etc/nginx/mime.types`, `include /etc/nginx/conf.d/*.conf`. `default.conf`: `listen 8080; root /usr/share/nginx/html;`. The package must not conflict with `nginx-stable-config`/`nginx-mainline-config` — the catalog does not install those.
- `tests/smoke/test_images.sh <image-ref> <image>` — run by the build workflow on amd64 before the gate:
  - all images: `docker run` with `--entrypoint /bin/sh` fails (no shell) for runtime variants; `docker inspect` user is `65532` (or `nonroot`); no `/sbin/apk`.
  - python: `python -c 'import ssl, sqlite3, zoneinfo; print(ssl.OPENSSL_VERSION)'` succeeds; dev: `uv --version`, `pip --version`, `/bin/sh -c true` succeed.
  - nginx: container answers `200` on `:8080/` within 5 s (a placeholder `index.html` is shipped in `/usr/share/nginx/html` by the config package).
  - static: a tiny static test binary (built in the workflow from `tests/smoke/hello.go` with `CGO_ENABLED=0`) copied in via a throwaway Dockerfile prints `ok` and can make a TLS request to `https://ghcr.io` (CA bundle works).
- [ ] **Step 1:** Write `test_images.sh` and `hello.go`.
- [ ] **Step 2:** Locally (or in a scratch workflow run) build each image with `melange build` + `apko build` and run the smoke script → it must fail first for nginx before `distroless-nginx-config` exists (no 8080 listener), then pass.
- [ ] **Step 3:** Commit.

### Task 7: Rescan decision and notifications

**Files:** Create `src/dltools/rescan.py`, `src/dltools/notify.py`, `tests/test_rescan.py`, `tests/test_notify.py`.

**Interfaces:**
- Consumes: `evaluate`'s Trivy parsing (Task 5).
- Produces:
  - `@dataclass RescanDecision(open_issue: bool, rebuild: bool, summary: str)`
  - `decide(report: dict, ignore: set[str], previous_ids: set[str]) -> RescanDecision` — new Critical/High IDs (not in `previous_ids`, not ignored) → `open_issue=True`; `rebuild=True` only if at least one of them has a `FixedVersion`.
  - `upsert_issue(title: str, body: str, label: str = "automation", runner=subprocess.run) -> None` — `gh issue list --label automation --state open --search "in:title <title>"`; comment on the existing one or `gh issue create`.
  - `dl rescan-decide --report r.json --ignore .trivyignore --previous prev-ids.txt` → JSON decision on stdout.
- [ ] **Step 1: Failing tests:** `test_rescan_fixed_critical_rebuilds`; `test_rescan_unfixed_opens_issue_without_rebuild`; `test_rescan_known_ids_no_issue`; `test_upsert_issue_comments_when_open` / `test_upsert_issue_creates_when_absent` (fake runner).
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** PASS → **Step 5:** commit.

### Task 8: Workflows — sync, build/publish, rescan

**Files:** Create `.github/workflows/sync.yml`, `.github/workflows/build.yml`, `.github/workflows/rescan.yml`, `.github/dependabot.yml`; finish `README.md`.

**Interfaces:**
- Consumes: `dl sync`, `dl lock-check` (CLI wrapper over `check_lock` added in this task), `dl tags`, `dl gate`, `dl rescan-decide`, `upsert_issue`; `melange/`, `tests/smoke/`.
- Produces: `dl matrix --locks locks/ --changed <git-diff-file-list>` → GitHub matrix JSON of `{image, line, variant}` (all when the list is empty or `catalog.yaml`/`melange/**` changed).

Behavior to implement (each a job/step; tool versions pinned, binaries verified by checksum, actions pinned by SHA):
- `sync.yml` — schedule `17 6 * * *` + `workflow_dispatch`; permissions `contents: write, issues: write`. Steps: `dl sync`; build the melange package (ephemeral signing key) so nginx configs can lock; `apko lock` each changed `*.apko.yaml`; `dl lock-check` each lock — a failing line is reverted to its previous committed files and gets an issue (`Sync blocked: <image>:<line>`); commit remaining changes to `main` as `chore(sync): <summary>` with the Co-Authored-By trailer; upsert issues for `line_added`, `line_removed`, `nginx_minor_changed` events and for warnings (e.g. endoflife.date unreachable). Push uses a token that triggers `build.yml` (GITHUB_TOKEN pushes don't trigger workflows — use `workflow_dispatch` of `build.yml` from `sync.yml` via `gh workflow run`).
- `build.yml` — on push to `main` touching `locks/**`, `catalog.yaml`, `melange/**`, `.trivyignore`; `workflow_dispatch` (inputs: optional image/line filter). Permissions `contents: read, packages: write, id-token: write, issues: write`. Matrix from `dl matrix`. Per entry: build melange pkg if nginx; `apko build --lockfile` to an OCI layout (both arches); load amd64 into Docker and run `tests/smoke/test_images.sh`; Trivy (`--format json`, both arches, against the local layout); fetch published report by scanning `ghcr.io/neilcar/distroless/<image>:<line-tag>` if it exists; `dl gate` per arch; on pass `crane push --index` the scanned layout to `…:<hash-tag>`, assert the pushed digest equals the layout's index digest, then `crane tag` the remaining tags from `dl tags`; `cosign sign --yes <ref>@<digest>`; `cosign attest --yes --type spdxjson --predicate <apko sbom>` per arch. The gate's Markdown table goes to `$GITHUB_STEP_SUMMARY`. Any failure → `upsert_issue("Build failed: <image>:<line>-<variant>", <run URL>)`.
- `rescan.yml` — schedule `47 7 * * *`; for every current line/variant tag, Trivy scan the published image, `dl rescan-decide` (previous IDs cached as a workflow artifact/cache keyed per tag); open issues; if any `rebuild`, `gh workflow run build.yml -f filter=<image>:<line>`.
- `.github/dependabot.yml` — `github-actions` weekly.
- [ ] **Step 1:** Write the three workflows and `dl matrix`/`dl lock-check` (+ `tests/test_matrix.py`: catalog change → all entries; single lock change → that entry only).
- [ ] **Step 2:** `uv run pytest` → PASS; `actionlint` on the workflows → clean.
- [ ] **Step 3:** Push `main` (this repo was requested public by the owner; pushing it is in scope). Run `sync.yml` by `workflow_dispatch`; expect it to commit locks for static `latest`, python `3.11`–`3.15` × runtime/dev, nginx `stable`/`mainline`, then trigger `build.yml`.
- [ ] **Step 4:** Verify each package is public: `docker logout ghcr.io; docker pull ghcr.io/neilcar/distroless/python:3.12` succeeds. If GHCR created them private, ask the owner to flip visibility in the package settings (no API for it) and re-verify.
- [ ] **Step 5:** Verify signatures and SBOMs: `cosign verify ghcr.io/neilcar/distroless/static:latest --certificate-identity-regexp 'https://github.com/neilcar/distroless/' --certificate-oidc-issuer https://token.actions.githubusercontent.com` and `cosign verify-attestation --type spdxjson …` succeed. Record each image's Trivy counts (expect 0 Critical / 0 High) in the README.
- [ ] **Step 6:** Prove the automation once: re-run `sync.yml` with no upstream change → no commit, no build. Commit README.

### Task 9: Switch trakt-clean

**Files (repo `neilcar/trakt-clean`):** Modify `Dockerfile`, `uv.lock` (certifi), `.github/dependabot.yml`, `deploy/values-home.yaml` only if its security context conflicts.

- [ ] **Step 1: Baseline.** `trivy image --format json ghcr.io/neilcar/trakt-clean:<current deployed tag>` (today `sha-9594fb8`); save counts (expected 1 Critical / 5 High / 16 Medium / 54 Low).
- [ ] **Step 2:** Branch `ops/distroless-base`. Dockerfile: build stage `ghcr.io/neilcar/distroless/python:3.12-dev@sha256:<digest>` (drop the `COPY --from=ghcr.io/astral-sh/uv` line; `uv` is in the dev image), `mkdir /data` in the build stage; runtime stage `ghcr.io/neilcar/distroless/python:3.12@sha256:<digest>`; no `RUN` in the runtime stage; `COPY --from=build --chown=10001:10001 /data /data`; keep `USER 10001:10001`, env, `VOLUME`, `EXPOSE`, `HEALTHCHECK`, `CMD` as today. `uv lock --upgrade-package certifi`.
- [ ] **Step 3:** Dependabot: add/confirm `package-ecosystem: docker` with an `ignore` for `ghcr.io/neilcar/distroless/python` `update-types: ["version-update:semver-major","version-update:semver-minor"]` so it bumps digests/patches but never moves the Python line.
- [ ] **Step 4:** Build locally, run the existing tests in the container and the healthcheck (`docker run` → `/healthz` 200 as uid 10001, `/data` writable). Trivy the new image; it must be strictly lower at every severity with 0 Critical and 0 High. If not, stop and report.
- [ ] **Step 5:** Commit; **ask the owner** before pushing/opening the PR. PR body: before/after Trivy table. After merge and CI image build, **ask the owner** before rolling out on the cluster; then verify the pod is Ready and `/healthz` is 200.

### Task 10: Switch atpass-web (port 8080)

**Files (repo `neilcar/atpass`):** Modify `web/Dockerfile`, `web/nginx.conf`, every other port-80 reference for the web image (find with `git grep -nE '\b80\b|:80|EXPOSE|8080' -- . ':!package-lock.json'` and review each hit: README/docs, compose files, release workflow test steps), `.github/dependabot.yml`, release notes/CHANGELOG.

- [ ] **Step 1: Baseline.** Trivy the current published Docker Hub `atpass-web` (latest release tag); save counts.
- [ ] **Step 2:** Branch. Runtime stage `FROM ghcr.io/neilcar/distroless/nginx:1.30@sha256:<digest>`; remove `RUN apk upgrade`; `COPY web/nginx.conf /etc/nginx/conf.d/default.conf` (now `listen 8080;`); `EXPOSE 8080`. Update all references found in Step 1's grep. Add a breaking-change note: "atpass-web now listens on port 8080 (was 80) and runs as non-root; update port mappings."
- [ ] **Step 3:** Dependabot docker entry with the same no-line-move `ignore` for `ghcr.io/neilcar/distroless/nginx`.
- [ ] **Step 4:** Build locally; `docker run -p 8080:8080` → app loads and SPA routes from `nginx.conf` still work; Trivy → fewer findings than baseline at every severity. If not, stop and report.
- [ ] **Step 5:** Commit; **ask the owner** before pushing/opening the PR (body: before/after table + breaking-change note).

### Task 11: Switch the Go watchers

**Files:** `neilcar/tailnet-egress-watcher` `Dockerfile` (both `prebuilt` and `source` stages) and `.github/dependabot.yml`; `neilcar/node-capacity-watcher` `Dockerfile` and `.github/dependabot.yml`.

- [ ] **Step 1: Baseline** both currently deployed images (expect 0 findings each).
- [ ] **Step 2:** Replace `gcr.io/distroless/static*:nonroot` with `ghcr.io/neilcar/distroless/static:latest@sha256:<digest>`; keep `USER 65532:65532` and entrypoints.
- [ ] **Step 3:** Dependabot docker entries so the digest gets bumped.
- [ ] **Step 4:** Build both; run each binary's `--help`/version or existing container smoke test; Trivy → still 0. tailnet-egress-watcher has its own image/release workflows; let its CI run on the PR.
- [ ] **Step 5:** Commit each; **ask the owner** before pushing/opening the two PRs.

### Task 12: Final verification

- [ ] **Step 1:** Table in `neilcar/distroless` README "Results": each consumer before/after (Critical/High/Medium/Low) from Tasks 9–11, and each base image's current counts.
- [ ] **Step 2:** Confirm the anti-goals: `git grep -n 'cgr.dev'` across all five repos returns nothing; every runtime image has no shell (smoke test output) and runs as non-root.
- [ ] **Step 3:** Commit and push the README update.
